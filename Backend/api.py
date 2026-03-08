import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from database import STORAGE_ROOT, Keys, Podcasts, PodcastTurns, Session, User, init_db
from podcast_jobs import create_job, get_artifact, get_job_status, process_job, stream_job_events
from schema import KeysCreate, PodcastJobCreate, UserInfo
from user import ServiceError, Users

import uvicorn

log_dir = Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "backend.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "Frontend"


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env(BASE_DIR / ".env")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(lifespan=lifespan)
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d  (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )


@app.get("/")
async def root_redirect():
    """Redirect bare root URL to hero page."""
    return RedirectResponse(url="/hero.html", status_code=302)


@app.post("/new_user", status_code=201)
def new_user(info: UserInfo):
    logger.info("Create user request received for email=%s", info.email)
    user = Users().new_user(info)
    return {"success": True, "data": user}


@app.post("/login")
def login(info: UserInfo):
    logger.info("Login request received for email=%s", info.email)
    user = Users().login_user(info)
    return {"success": True, "data": user}


@app.get("/auth/config")
def auth_config():
    return {"googleClientId": GOOGLE_CLIENT_ID}


@app.post("/settings/keys", status_code=200)
def save_keys(payload: KeysCreate):
    """Upsert a Grok or OpenRouter API key for a user (keyed by email)."""
    session = Session()
    try:
        row = session.query(Keys).filter(Keys.useremail == payload.useremail).first()
        if row is None:
            # Create a new row; fill the other column with empty string (nullable=False)
            row = Keys(
                useremail=payload.useremail,
                grokApi="" if payload.key_type == "openrouter" else payload.key_value,
                openrouterApi="" if payload.key_type == "grok" else payload.key_value,
            )
            session.add(row)
        else:
            if payload.key_type == "grok":
                row.grokApi = payload.key_value  #type:ignore
            else:
                row.openrouterApi = payload.key_value  #type:ignore
        session.commit()
        return {"success": True, "message": "Key saved."}
    except Exception as exc:
        session.rollback()
        logger.exception("Failed to save key for %s", payload.useremail)
        raise ServiceError(status_code=500, detail=f"Could not save key: {exc}")
    finally:
        session.close()


@app.get("/settings/keys")
def get_keys(email: str):
    """Return existing (non-empty) API keys for the given user email."""
    session = Session()
    try:
        row = session.query(Keys).filter(Keys.useremail == email).first()
        if row is None:
            return {"success": True, "data": {"grokApi": "", "openrouterApi": ""}}
        return {
            "success": True,
            "data": {
                "grokApi":       row.grokApi        or "",
                "openrouterApi": row.openrouterApi  or "",
            },
        }
    finally:
        session.close()


@app.post("/podcasts/jobs", status_code=201)
async def create_podcast_job(payload: PodcastJobCreate):
    status = await asyncio.to_thread(create_job, payload)
    asyncio.create_task(process_job(status.job_id))
    return {"success": True, "data": status.model_dump()}


@app.get("/podcasts/jobs/{job_id}")
async def podcast_job_status(job_id: int):
    status = await asyncio.to_thread(get_job_status, job_id)
    return {"success": True, "data": status.model_dump()}


@app.get("/podcasts/jobs/{job_id}/stream")
async def podcast_job_stream(job_id: int):
    _ = await asyncio.to_thread(get_job_status, job_id)
    return StreamingResponse(
        stream_job_events(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/podcasts/history")
async def podcast_history(email: str = Query(..., description="User email address")):
    """Return all podcasts for a given user, newest first."""
    def _query():
        session = Session()
        try:
            user = session.query(User).filter(User.email == email).first()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            rows = (
                session.query(Podcasts)
                .filter(Podcasts.userid == user.id)
                .order_by(Podcasts.created_at.desc())
                .all()
            )
            return [
                {
                    "podcast_id": r.id,
                    "status": r.status,
                    "style": r.style,
                    "exchanges": r.exchanges,
                    "source_url": r.source_url,
                    "audio_location": r.audio_location,
                    "script_location": r.script_location,
                    "created_at": (ca.isoformat() if (ca := getattr(r, "created_at", None)) else None),
                    "error_message": r.error_message,
                }
                for r in rows
            ]
        finally:
            session.close()

    data = await asyncio.to_thread(_query)
    return {"success": True, "data": data}


@app.get("/podcasts/{podcast_id}/turns")
async def podcast_turns(podcast_id: int):
    """Return all turns (transcript + audio chunks) for a podcast, in order."""
    def _query():
        session = Session()
        try:
            turns = (
                session.query(PodcastTurns)
                .filter(PodcastTurns.podcast_id == podcast_id)
                .order_by(PodcastTurns.turn_index)
                .all()
            )
            return [
                {
                    "turn_index": t.turn_index,
                    "speaker": t.speaker,
                    "text": t.text,
                    "audio_chunk_url": t.audio_chunk_location,
                }
                for t in turns
            ]
        finally:
            session.close()

    data = await asyncio.to_thread(_query)
    return {"success": True, "data": data}


@app.get("/podcasts/{podcast_id}")
async def get_podcast_artifact(podcast_id: int):
    artifact = await asyncio.to_thread(get_artifact, podcast_id)
    return {"success": True, "data": artifact.model_dump()}


app.mount("/storage", StaticFiles(directory=str(STORAGE_ROOT), html=False), name="storage")

# Must be mounted after API routes so API paths take priority
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)
