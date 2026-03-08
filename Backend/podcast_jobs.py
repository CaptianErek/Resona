"""
podcast_jobs.py — Full LLM + TTS pipeline for Resona.

Flow per job:
  1. Look up the user's API keys from the Keys table (fail early if missing).
  2. Fetch + clean the blog source text.
  3. For each exchange turn:
       a. Call OpenRouter (primary) or Groq (fallback) to generate the speaker line.
       b. Save the script line to the DB + publish turn_text_ready SSE.
       c. Call Groq TTS to convert the line to a WAV chunk.
       d. Save the chunk path to the DB + publish turn_audio_ready SSE.
  4. Merge all chunk WAVs into one final audio file.
  5. Save the final script text + audio paths on the Podcasts row.

LLM model selection (lightweight reasoning models):
  - OpenRouter: uses google/gemini-flash-1.5 (host) and mistralai/mistral-7b-instruct (guest)
  - Groq fallback: llama3-8b-8192 (host) and mixtral-8x7b-32768 (guest)

Style → persona mapping:
  Interview   → Host asks probing questions, Guest answers with expertise
  Debate      → Host argues one side, Guest argues the counter-position
  Casual Chat → Two friends chatting, Host leads, Guest reacts informally
  Storytelling→ Host narrates, Guest provides colour commentary / reactions
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import wave
from contextlib import suppress
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.request import Request, urlopen

import httpx
import numpy as np
from fastapi import HTTPException
from groq import Groq as GroqClient
from scipy.io import wavfile
from sqlalchemy.orm import Session as DbSession

from database import (
    FINAL_AUDIO_ROOT,
    SCRIPT_ROOT,
    STORAGE_ROOT,
    Keys,
    PodcastTurns,
    Podcasts,
    Session,
    User,
    chunks_dir_for_job,
)
from schema import PodcastArtifact, PodcastJobCreate, PodcastJobStatus

logger = logging.getLogger(__name__)

# ─── Tuneable constants ────────────────────────────────────────────────────────
MAX_SOURCE_CHARS = 6000           # chars fed into each LLM prompt
MAX_SOURCE_DOWNLOAD_BYTES = 600_000
GENERATION_TIMEOUT_SEC = 60      # per LLM call
TTS_TIMEOUT_SEC = 60             # per TTS call
JOB_CONCURRENCY_LIMIT = 1
JOB_SEMAPHORE = asyncio.Semaphore(JOB_CONCURRENCY_LIMIT)

# ─── OpenRouter models (primary) ──────────────────────────────────────────────
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_HOST_MODEL  = "arcee-ai/trinity-large-preview:free"
OPENROUTER_GUEST_MODEL = "liquid/lfm-2.5-1.2b-instruct:free"

# ─── Groq models (fallback LLM + TTS) ─────────────────────────────────────────
GROQ_HOST_MODEL  = "qwen/qwen3-32b"
GROQ_GUEST_MODEL = "moonshotai/kimi-k2-instruct-0905"
GROQ_TTS_MODEL   = "canopylabs/orpheus-v1-english"

# Orpheus English voices (troy=male host, diana=female guest)
GROQ_HOST_VOICE  = "troy"
GROQ_GUEST_VOICE = "diana"


# ─── Style → system-prompt personas ───────────────────────────────────────────
STYLE_PERSONAS: dict[str, dict[str, str]] = {
    "Interview": {
        "host": (
            "You are the HOST of a podcast interview. Your role is to ask insightful, "
            "probing questions about the blog content provided. Stay strictly on topic. "
            "Keep your turn to 2–4 sentences."
        ),
        "guest": (
            "You are the GUEST expert being interviewed about the blog content provided. "
            "Give informed, thoughtful answers based solely on the blog. "
            "Keep your turn to 3–5 sentences."
        ),
    },
    "Debate": {
        "host": (
            "You are the HOST of a debate podcast. You argue IN FAVOUR of the main "
            "point raised in the blog content. Be persuasive but reference only things "
            "from the blog. Keep your turn to 2–4 sentences."
        ),
        "guest": (
            "You are the GUEST debater. You argue AGAINST or provide counterpoints to "
            "the main claim in the blog content. Be logical and stay on topic. "
            "Keep your turn to 2–4 sentences."
        ),
    },
    "Casual Chat": {
        "host": (
            "You are HOST of a casual, friendly podcast. You lead a relaxed conversation "
            "about the blog content — share opinions naturally, no jargon. "
            "Keep your turn to 2–3 sentences."
        ),
        "guest": (
            "You are GUEST on a casual podcast. React informally and personally to what "
            "the host says, drawing only on the blog content. Keep your turn to 2–3 sentences."
        ),
    },
    "Storytelling": {
        "host": (
            "You are the HOST narrator of a storytelling podcast. Narrate the key ideas "
            "from the blog as an engaging story. Stay faithful to the blog content. "
            "Keep your turn to 3–5 sentences."
        ),
        "guest": (
            "You are GUEST co-narrator providing vivid colour commentary and reactions to "
            "what the host just said, grounded in the blog content. Keep your turn to 2–3 sentences."
        ),
    },
}

DEFAULT_STYLE_PERSONA = {
    "host": (
        "You are the HOST of a podcast. Discuss the blog content naturally. "
        "Keep your turn to 3–4 sentences."
    ),
    "guest": (
        "You are the GUEST on a podcast. Respond to the host about the blog content. "
        "Keep your turn to 3–4 sentences."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# SSE Broker
# ═══════════════════════════════════════════════════════════════════════════════

class JobEventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, job_id: int, event: str, payload: dict[str, Any]) -> None:
        msg = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        async with self._lock:
            subscribers = list(self._subscribers.get(job_id, set()))
        for queue in subscribers:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(msg)

    async def subscribe(self, job_id: int) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers.setdefault(job_id, set()).add(queue)
        return queue

    async def unsubscribe(self, job_id: int, queue: asyncio.Queue[str]) -> None:
        async with self._lock:
            existing = self._subscribers.get(job_id)
            if not existing:
                return
            existing.discard(queue)
            if not existing:
                self._subscribers.pop(job_id, None)


broker = JobEventBroker()


# ═══════════════════════════════════════════════════════════════════════════════
# Source text fetching
# ═══════════════════════════════════════════════════════════════════════════════

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_ignored_tag = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "noscript"}:
            self._in_ignored_tag = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._in_ignored_tag = False

    def handle_data(self, data: str) -> None:
        if self._in_ignored_tag:
            return
        if data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return " ".join(self._chunks)


def _clean_html(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw_html)
    text = parser.text()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_source_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=12) as response:  # nosec B310
        body = response.read(MAX_SOURCE_DOWNLOAD_BYTES).decode("utf-8", errors="ignore")
    cleaned = _clean_html(body)
    if not cleaned:
        raise ValueError("Unable to extract readable text from URL")
    return cleaned[:MAX_SOURCE_CHARS]


# ═══════════════════════════════════════════════════════════════════════════════
# Retry wrapper
# ═══════════════════════════════════════════════════════════════════════════════

async def _with_retries(coro_factory, retries: int = 2, timeout: int = 60):
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


# ═══════════════════════════════════════════════════════════════════════════════
# LLM: turn-text generation with OpenRouter primary / Groq fallback
# ═══════════════════════════════════════════════════════════════════════════════

def _build_messages(
    style: str,
    role: str,          # "host" | "guest"
    source_text: str,
    conversation_history: list[dict],
) -> list[dict]:
    """Build the chat messages list for one turn."""
    personas = STYLE_PERSONAS.get(style, DEFAULT_STYLE_PERSONA)
    system_prompt = (
        f"{personas[role]}\n\n"
        f"=== BLOG CONTENT (your only source of truth) ===\n{source_text}\n"
        "=== END OF BLOG CONTENT ===\n\n"
        "IMPORTANT: Do NOT reference anything outside the blog content above. "
        "Do NOT add disclaimers. Speak naturally, as if on a real podcast."
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": "Your turn. Speak now."})
    return messages


async def _call_openrouter(
    api_key: str,
    model: str,
    messages: list[dict],
) -> str:
    """Call OpenRouter chat completions API and return the assistant text."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://resona.app",
        "X-Title": "Resona Podcast",
    }
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.75,
    }

    async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT_SEC) as client:
        resp = await client.post(OPENROUTER_API_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    # OpenRouter mirrors OpenAI response shape
    text = data["choices"][0]["message"]["content"].strip()
    if not text:
        raise ValueError("Empty response from OpenRouter")
    return text


async def _call_groq_llm(
    api_key: str,
    model: str,
    messages: list[dict],
) -> str:
    """Call Groq chat completions and return the assistant text."""
    client = GroqClient(api_key=api_key)

    def _sync_call():
        resp = client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=300,
            temperature=0.75,
        )
        return resp.choices[0].message.content or ""

    text = await asyncio.to_thread(_sync_call)
    text = text.strip()
    if not text:
        raise ValueError("Empty response from Groq LLM")
    return text


async def _generate_turn_text(
    style: str,
    role: str,
    source_text: str,
    conversation_history: list[dict],
    openrouter_key: str,
    groq_key: str,
    openrouter_model: str,
    groq_model: str,
) -> str:
    """Generate one turn of dialogue, OpenRouter first, Groq on any error."""
    messages = _build_messages(style, role, source_text, conversation_history)

    # Primary: OpenRouter
    if openrouter_key:
        try:
            return await _call_openrouter(openrouter_key, openrouter_model, messages)
        except Exception as exc:
            logger.warning("OpenRouter failed (%s), falling back to Groq", exc)

    # Fallback: Groq
    if groq_key:
        return await _call_groq_llm(groq_key, groq_model, messages)

    raise RuntimeError("No LLM API keys available to generate dialogue.")


# ═══════════════════════════════════════════════════════════════════════════════
# TTS: Groq playai-tts → WAV chunk
# ═══════════════════════════════════════════════════════════════════════════════

def _synthesize_tts_sync(
    groq_key: str,
    text: str,
    voice: str,
    output_path: Path,
) -> None:
    """Blocking call to Groq TTS; writes a WAV file at output_path."""
    client = GroqClient(api_key=groq_key)
    response = client.audio.speech.create(
        model=GROQ_TTS_MODEL,
        voice=voice,
        input=text,
        response_format="wav",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.read())


async def _synthesize_turn_audio(
    groq_key: str,
    job_id: int,
    turn_index: int,
    text: str,
    voice: str,
) -> Path:
    """Async wrapper for TTS synthesis. Writes chunk WAV, returns its path."""
    chunks_dir = chunks_dir_for_job(job_id)
    audio_path = chunks_dir / f"turn_{turn_index:03d}.wav"
    await asyncio.to_thread(_synthesize_tts_sync, groq_key, text, voice, audio_path)
    return audio_path


# ═══════════════════════════════════════════════════════════════════════════════
# WAV merging
# ═══════════════════════════════════════════════════════════════════════════════

def _write_silent_wav(path: Path, duration_sec: float = 1.2, sample_rate: int = 22050) -> None:
    n_frames = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        silent_frame = (0).to_bytes(2, byteorder="little", signed=True)
        wav_file.writeframes(silent_frame * n_frames)


def _merge_wav_files(chunk_paths: list[Path], output_path: Path) -> None:
    """Merge WAV chunks into one file using scipy to avoid the 32-bit WAV header limit."""
    valid_paths = [p for p in chunk_paths if p.exists() and p.stat().st_size > 44]
    if not valid_paths:
        _write_silent_wav(output_path, duration_sec=0.4)
        return

    try:
        # Read first chunk to get the canonical sample rate
        ref_rate, ref_data = wavfile.read(str(valid_paths[0]))

        arrays: list[np.ndarray] = [ref_data]
        for chunk_path in valid_paths[1:]:
            rate, data = wavfile.read(str(chunk_path))
            if rate != ref_rate:
                logger.warning("Skipping mismatched sample rate chunk: %s (%d vs %d)", chunk_path, rate, ref_rate)
                continue
            # Ensure mono: if stereo average the channels
            if data.ndim == 2 and ref_data.ndim == 1:
                data = data.mean(axis=1).astype(ref_data.dtype)
            arrays.append(data)

        merged = np.concatenate(arrays, axis=0)
        wavfile.write(str(output_path), ref_rate, merged)
        logger.info("Merged %d chunks → %s (%d samples)", len(arrays), output_path.name, len(merged))

    except Exception as exc:
        logger.exception("WAV merge failed (%s); writing silent placeholder", exc)
        _write_silent_wav(output_path, duration_sec=0.4)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _relative_storage_url(path: Path) -> str:
    rel = path.relative_to(STORAGE_ROOT).as_posix()
    return f"/storage/{rel}"


def _compute_progress(session: DbSession, job: Podcasts) -> int:
    if job.status == "completed":  # type: ignore
        return 100
    if job.status == "failed":  # type: ignore
        return 100
    if job.exchanges <= 0:  # type: ignore
        return 0
    ready_count = session.query(PodcastTurns).filter(PodcastTurns.podcast_id == job.id).count()
    ratio = min(1.0, ready_count / max(1, int(job.exchanges)))  # type: ignore
    return int(ratio * 90)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API: create_job / get_job_status / get_artifact / process_job
# ═══════════════════════════════════════════════════════════════════════════════

def create_job(payload: PodcastJobCreate) -> PodcastJobStatus:
    session = Session()
    try:
        user = session.query(User).filter(User.email == payload.user_email).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        key_row = session.query(Keys).filter(Keys.useremail == payload.user_email).first()
        if key_row is None or (not key_row.openrouterApi and not key_row.grokApi):  #type:ignore
            raise HTTPException(
                status_code=400,
                detail="No API keys found — please add them in Settings.",
            )

        job = Podcasts(
            userid=user.id,  # type: ignore[arg-type]
            status="queued",
            source_url=payload.url,
            style=payload.style,
            exchanges=payload.exchanges,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        logger.info("Podcast job created: job_id=%s style=%s", job.id, job.style)
        return PodcastJobStatus(
            job_id=job.id,  # type: ignore
            status=job.status,  # type: ignore
            progress=0,
            error=None,
            podcast_id=None,
        )
    finally:
        session.close()


def get_job_status(job_id: int) -> PodcastJobStatus:
    session = Session()
    try:
        job = session.query(Podcasts).filter(Podcasts.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return PodcastJobStatus(
            job_id=job.id,  # type: ignore
            status=job.status,  # type: ignore
            progress=_compute_progress(session, job),
            error=job.error_message,  # type: ignore
            podcast_id=job.id if job.status == "completed" else None,  # type: ignore
        )
    finally:
        session.close()


def get_artifact(podcast_id: int) -> PodcastArtifact:
    session = Session()
    try:
        job = session.query(Podcasts).filter(Podcasts.id == podcast_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Podcast not found")
        if job.status != "completed":  # type: ignore
            raise HTTPException(status_code=409, detail="Podcast is not completed yet")
        return PodcastArtifact(
            podcast_id=job.id,  # type: ignore
            script_download_url=job.script_location,  # type: ignore
            audio_download_url=job.audio_location,  # type: ignore
            metadata={
                "status": job.status,
                "style": job.style,
                "exchanges": job.exchanges,
                "source_url": job.source_url,
                "created_at": job.created_at.isoformat() if isinstance(job.created_at, datetime) else None,
                "updated_at": job.updated_at.isoformat() if isinstance(job.updated_at, datetime) else None,
            },
        )
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Main job processor
# ═══════════════════════════════════════════════════════════════════════════════

async def process_job(job_id: int) -> None:  # noqa: C901
    async with JOB_SEMAPHORE:
        session = Session()
        try:
            # ── 1. Load job ──────────────────────────────────────────────────
            job = session.query(Podcasts).filter(Podcasts.id == job_id).first()
            if job is None:
                logger.error("Job %s disappeared before processing", job_id)
                return

            job.status = "in_progress"  # type: ignore
            job.error_message = None  # type: ignore
            session.commit()
            logger.info("Job %s started (style=%s, exchanges=%s)", job_id, job.style, job.exchanges)

            # ── 2. Load API keys ─────────────────────────────────────────────
            key_row = session.query(Keys).filter(
                Keys.useremail == session.query(User).filter(
                    User.id == job.userid
                ).first().email  # type: ignore
            ).first()

            if key_row is None:
                raise RuntimeError("API keys not found for this user.")

            openrouter_key: str = key_row.openrouterApi or ""  # type: ignore
            groq_key: str = key_row.grokApi or ""              # type: ignore

            if not openrouter_key and not groq_key:
                raise RuntimeError("Both OpenRouter and Groq API keys are empty.")

            if not groq_key:
                raise RuntimeError("Groq API key is required for TTS (audio generation).")

            # ── 3. Fetch blog source text ────────────────────────────────────
            source_text = await _with_retries(
                lambda: asyncio.to_thread(fetch_source_text, job.source_url),  # type: ignore
                retries=1,
                timeout=30,
            )
            logger.info("Job %s: fetched %d chars from source", job_id, len(source_text))

            # ── 4. Turn-by-turn generation ───────────────────────────────────
            style: str = job.style  # type: ignore
            total_turns: int = int(job.exchanges)  # type: ignore

            script_lines: list[str] = []
            chunk_paths: list[Path] = []
            conversation_history: list[dict] = []   # grows with each turn

            for turn_index in range(1, total_turns + 1):
                is_host   = (turn_index % 2 == 1)
                role      = "host" if is_host else "guest"
                speaker   = "Host" if is_host else "Guest"
                tts_voice = GROQ_HOST_VOICE if is_host else GROQ_GUEST_VOICE
                or_model  = OPENROUTER_HOST_MODEL if is_host else OPENROUTER_GUEST_MODEL
                gr_model  = GROQ_HOST_MODEL if is_host else GROQ_GUEST_MODEL  # same across all styles

                await broker.publish(
                    job_id, "turn_started",
                    {"type": "turn_started", "job_id": job_id,
                     "turn_index": turn_index, "speaker": speaker},
                )

                # ── 4a. Generate turn text ───────────────────────────────────
                turn_text = await _with_retries(
                    lambda r=role, orm=or_model, grm=gr_model: _generate_turn_text(
                        style=style,
                        role=r,
                        source_text=source_text,
                        conversation_history=conversation_history,
                        openrouter_key=openrouter_key,
                        groq_key=groq_key,
                        openrouter_model=orm,
                        groq_model=grm,
                    ),
                    retries=2,
                    timeout=GENERATION_TIMEOUT_SEC,
                )

                # Append to conversation history so next speaker replies to this one
                conversation_history.append({"role": "assistant", "content": turn_text})

                # ── 4b. Persist turn text ────────────────────────────────────
                turn_row = PodcastTurns(
                    podcast_id=job_id,
                    turn_index=turn_index,
                    speaker=speaker,
                    text=turn_text,
                )
                session.add(turn_row)
                session.commit()

                script_lines.append(f"{speaker}: {turn_text}")

                await broker.publish(
                    job_id, "turn_text_ready",
                    {
                        "type": "turn_text_ready",
                        "job_id": job_id,
                        "turn_index": turn_index,
                        "speaker": speaker,
                        "text": turn_text,
                    },
                )

                # ── 4c. TTS → WAV chunk ──────────────────────────────────────
                chunk_path = await _with_retries(
                    lambda ti=turn_index, t=turn_text, v=tts_voice: _synthesize_turn_audio(
                        groq_key=groq_key,
                        job_id=job_id,
                        turn_index=ti,
                        text=t,
                        voice=v,
                    ),
                    retries=2,
                    timeout=TTS_TIMEOUT_SEC,
                )
                chunk_url = _relative_storage_url(chunk_path)
                chunk_paths.append(chunk_path)

                turn_row.audio_chunk_location = chunk_url  # type: ignore
                session.commit()

                await broker.publish(
                    job_id, "turn_audio_ready",
                    {
                        "type": "turn_audio_ready",
                        "job_id": job_id,
                        "turn_index": turn_index,
                        "speaker": speaker,
                        "audio_chunk_url": chunk_url,
                    },
                )

                logger.info("Job %s: turn %d/%d done", job_id, turn_index, total_turns)

            # ── 5. Save script text ──────────────────────────────────────────
            final_script_text = "\n".join(script_lines)
            script_path = SCRIPT_ROOT / f"podcast_{job_id}.txt"
            script_path.write_text(final_script_text, encoding="utf-8")

            # ── 6. Merge chunks → final WAV ──────────────────────────────────
            final_audio_path = FINAL_AUDIO_ROOT / f"podcast_{job_id}.wav"
            await asyncio.to_thread(_merge_wav_files, chunk_paths, final_audio_path)

            # ── 7. Mark completed ────────────────────────────────────────────
            job.script_text     = final_script_text                         # type: ignore
            job.script_location = _relative_storage_url(script_path)        # type: ignore
            job.audio_location  = _relative_storage_url(final_audio_path)   # type: ignore
            job.status          = "completed"                                # type: ignore
            job.error_message   = None                                       # type: ignore
            session.commit()

            logger.info("Job %s completed successfully", job_id)
            await broker.publish(
                job_id, "job_completed",
                {
                    "type": "job_completed",
                    "job_id": job_id,
                    "podcast_id": job_id,
                    "script_download_url": job.script_location,
                    "audio_download_url":  job.audio_location,
                },
            )

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            try:
                job = session.query(Podcasts).filter(Podcasts.id == job_id).first()
                if job is not None:
                    job.status = "failed"           # type: ignore
                    job.error_message = str(exc)    # type: ignore
                    session.commit()
            except Exception:
                pass

            logger.exception("Job %s failed: %s", job_id, exc)
            await broker.publish(
                job_id, "job_failed",
                {"type": "job_failed", "job_id": job_id, "error": str(exc)},
            )
        finally:
            session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SSE stream
# ═══════════════════════════════════════════════════════════════════════════════

TERMINAL_EVENT_TYPES = frozenset({"job_completed", "job_failed"})


async def stream_job_events(job_id: int) -> AsyncIterator[str]:
    queue = await broker.subscribe(job_id)
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=45)
                yield item
                try:
                    _, _, data_part = item.partition("data:")
                    payload = json.loads(data_part.strip())
                    if payload.get("type") in TERMINAL_EVENT_TYPES:
                        break
                except Exception:
                    pass
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"
    finally:
        await broker.unsubscribe(job_id, queue)
