const API_BASE = "http://localhost:8000";

const statusEl        = document.getElementById("jobStatus");
const transcriptEl    = document.getElementById("transcript");
const audioEl         = document.getElementById("liveAudio");
const audioInfoEl     = document.getElementById("audioInfo");
const scriptDownloadEl= document.getElementById("scriptDownload");
const audioDownloadEl = document.getElementById("audioDownload");
const errorMessageEl  = document.getElementById("errorMessage");

const params = new URLSearchParams(window.location.search);
const jobId  = Number(params.get("job_id"));

// ── State ──────────────────────────────────────────────────────────────────────
let source        = null;
let pollTimer     = null;
let nextPlayTurn  = 1;          // next turn we are waiting to play
let isPlaying     = false;      // whether we are currently playing a turn

// Pending data received from SSE, keyed by turn_index
// Each entry: { text?: string, audioUrl?: string, speaker?: string }
const pendingTurns = new Map();

// ── Helpers ────────────────────────────────────────────────────────────────────
function setStatus(text) { statusEl.textContent = text; }
function setError(text)  { errorMessageEl.textContent = text || ""; }

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function appendTranscript(turnIndex, speaker, text) {
    const line = document.createElement("div");
    line.className = "transcript-line";
    line.dataset.turn = turnIndex;
    line.innerHTML = `<span class="transcript-speaker">Turn ${turnIndex} – ${speaker}:</span> ${text}`;
    transcriptEl.appendChild(line);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    return line;
}

function highlightActiveTurn(activeLine) {
    document.querySelectorAll(".transcript-line").forEach(el => {
        el.classList.remove("active-turn");
    });
    if (activeLine) activeLine.classList.add("active-turn");
}

function enableDownloads(scriptUrl, audioUrl) {
    if (scriptUrl) {
        scriptDownloadEl.href = scriptUrl;
        scriptDownloadEl.classList.remove("disabled");
    }
    if (audioUrl) {
        audioDownloadEl.href = audioUrl;
        audioDownloadEl.classList.remove("disabled");
    }
}

// ── Core playback pump ─────────────────────────────────────────────────────────
// Called whenever new data arrives. Picks up any complete (text + audio) turns
// in order and plays them one-by-one.
async function pumpQueue() {
    if (isPlaying) return;   // already running – it will loop by itself
    isPlaying = true;

    while (true) {
        const turn = pendingTurns.get(nextPlayTurn);
        if (!turn || !turn.text || !turn.audioUrl) break;  // not ready yet

        pendingTurns.delete(nextPlayTurn);

        // 1. Show the text for this turn
        const line = appendTranscript(nextPlayTurn, turn.speaker, turn.text);
        highlightActiveTurn(line);
        audioInfoEl.textContent = `Playing turn ${nextPlayTurn} – ${turn.speaker}…`;

        // 2. Play the audio chunk at the same time
        try {
            audioEl.src = `${API_BASE}${turn.audioUrl}`;
            await audioEl.play();
            await new Promise(resolve => {
                const done = () => {
                    audioEl.removeEventListener("ended", done);
                    audioEl.removeEventListener("error", done);
                    resolve();
                };
                audioEl.addEventListener("ended", done);
                audioEl.addEventListener("error", done);
            });
        } catch {
            await sleep(200);   // autoplay blocked or error; continue anyway
        }

        // 3. Remove highlight and advance
        highlightActiveTurn(null);
        nextPlayTurn += 1;
    }

    isPlaying = false;
}

// ── SSE event handler ──────────────────────────────────────────────────────────
function handleEventMessage(type, payload) {
    if (type === "turn_started") {
        setStatus(`Generating turn ${payload.turn_index}…`);
    }

    if (type === "turn_text_ready") {
        // Buffer the text; don't show it yet
        const entry = pendingTurns.get(payload.turn_index) || {};
        entry.text    = payload.text;
        entry.speaker = payload.speaker;
        pendingTurns.set(payload.turn_index, entry);
        // Try to advance the pump in case audio already arrived
        pumpQueue();
    }

    if (type === "turn_audio_ready") {
        // Buffer the audio URL; don't play yet
        const entry = pendingTurns.get(payload.turn_index) || {};
        entry.audioUrl = payload.audio_chunk_url;
        pendingTurns.set(payload.turn_index, entry);
        // Try to advance the pump
        pumpQueue();
    }

    if (type === "job_completed") {
        setStatus("completed");
        enableDownloads(payload.script_download_url, payload.audio_download_url);
        setError("");
        stopPolling();
        if (source) { source.close(); source = null; }
    }

    if (type === "job_failed") {
        setStatus("failed");
        setError(payload.error || "Job failed");
        stopPolling();
        if (source) { source.close(); source = null; }
    }
}

// ── Status polling (fallback if SSE drops) ─────────────────────────────────────
async function fetchStatus() {
    const response = await fetch(`${API_BASE}/podcasts/jobs/${jobId}`);
    const payload  = await response.json();
    if (!response.ok || !payload.success) throw new Error(payload.error || "Failed to fetch status");

    const data = payload.data;
    setStatus(`${data.status} (${data.progress}%)`);

    if (data.status === "completed" && data.podcast_id) {
        const ar = await fetch(`${API_BASE}/podcasts/${data.podcast_id}`);
        const ap = await ar.json();
        if (ar.ok && ap.success) {
            enableDownloads(ap.data.script_download_url, ap.data.audio_download_url);
            setError("");
        }
        stopPolling();
    }

    if (data.status === "failed") {
        setError(data.error || "Job failed");
        stopPolling();
    }
}

function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(() => fetchStatus().catch(err => setError(err.message || "Polling error")), 3000);
}

function stopPolling() {
    if (!pollTimer) return;
    clearInterval(pollTimer);
    pollTimer = null;
}

// ── SSE stream ─────────────────────────────────────────────────────────────────
function startStream() {
    source = new EventSource(`${API_BASE}/podcasts/jobs/${jobId}/stream`);

    ["turn_started", "turn_text_ready", "turn_audio_ready", "job_completed", "job_failed"].forEach(eventType => {
        source.addEventListener(eventType, event => {
            handleEventMessage(eventType, JSON.parse(event.data));
        });
    });

    source.onerror = () => {
        setError("Live stream disconnected, using status polling.");
        if (source) { source.close(); source = null; }
        startPolling();
    };
}

// ── Boot ───────────────────────────────────────────────────────────────────────
if (!Number.isInteger(jobId) || jobId <= 0) {
    setStatus("invalid");
    setError("Missing or invalid job_id in URL.");
} else {
    setStatus("queued");
    startStream();
    fetchStatus().catch(err => {
        setError(err.message || "Unable to fetch initial status");
        startPolling();
    });
}
