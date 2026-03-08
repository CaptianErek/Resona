# Resona — Blog to Podcast

> **Turn any blog post into a dual-host AI podcast in seconds.**

Resona takes a public blog URL and generates a fully scripted, text-to-speech podcast conversation between two AI hosts. The dialogue is streamed turn-by-turn in real time so you can hear it as it's being generated.

---

## ✨ Features

- 🔗 **URL-based ingestion** — paste any public blog/article URL
- 🎙️ **Dual-host AI dialogue** — Host A and Host B alternate in Interview, Debate, Casual Chat, or Storytelling styles
- ⚡ **Real-time streaming** — each turn is generated and spoken immediately via SSE
- 📥 **Downloadable artifacts** — full script (`.txt`) and merged audio (`.mp3`) on completion
- 🔐 **Auth** — email/password or Google Sign-In
- 📚 **History** — browse and replay all previously generated podcasts
- ⚙️ **Settings** — manage your OpenRouter and Grok API keys per account

---

## 🏗️ Project Structure

```
Blog to Podcast/
├── Backend/                  # FastAPI backend
│   ├── api.py                # Route definitions & app entry point
│   ├── chat.py               # LLM dialogue orchestration
│   ├── database.py           # SQLAlchemy models & DB init (SQLite)
│   ├── podcast_jobs.py       # Background job processor & SSE emitter
│   ├── schema.py             # Pydantic request/response models
│   ├── user.py               # User creation & login logic
│   └── .env                  # API keys / secrets (⚠️ never commit)
│
├── Frontend/                 # Vanilla HTML/CSS/JS pages
│   ├── hero.html             # Landing / marketing page
│   ├── new.html              # Sign-up page
│   ├── login.html            # Login page
│   ├── studio.html           # Podcast creation studio
│   ├── generated.html        # Real-time streaming playback page
│   ├── previous.html         # Podcast history & replay
│   ├── setting.html          # API key management
│   ├── Config/               # Frontend config (Google Client ID etc.)
│   ├── Images/               # Static image assets
│   └── Videos/               # Static video assets
│
├── storage/                  # Generated media files (⚠️ never commit)
│   ├── audio/
│   │   ├── chunks/           # Per-turn audio chunks
│   │   └── final/            # Merged final podcast audio files
│   └── scripts/              # Generated full-script text files
│
├── logs/                     # Backend log files (auto-created)
├── resona.db                 # SQLite database (⚠️ never commit)
├── package.json              # Node.js dependencies (dotenv)
└── README.md                 # You are here
```

---

## 🚀 Getting Started

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| pip | latest |
| Node.js | 18+ (for `dotenv`) |

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd "Blog to Podcast"
```

### 2. Set up the Python environment

```bash
cd Backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install fastapi uvicorn sqlalchemy pydantic openai requests beautifulsoup4 pydub httpx
```

### 3. Configure environment variables

Copy the example env file and fill in your secrets:

```bash
cp Backend/.env.example Backend/.env
```

Edit `Backend/.env`:

```env
GOOGLE_CLIENT_ID=your-google-oauth-client-id
OPENROUTER_API_KEY=your-openrouter-key     # optional — can be set per user in Settings
GROK_API_KEY=your-grok-key                 # optional — fallback LLM provider
```

### 4. Install Node dependencies (optional)

```bash
npm install
```

### 5. Start the backend

```bash
cd Backend
uvicorn api:app --reload --host localhost --port 8000
```

Open [http://localhost:8000](http://localhost:8000) — the backend also serves the entire Frontend automatically.

---

## 🔌 API Overview

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/new_user` | Register a new user |
| `POST` | `/login` | Log in an existing user |
| `GET` | `/auth/config` | Return Google OAuth client ID |
| `POST` | `/settings/keys` | Save/update a user's API key |
| `GET` | `/settings/keys?email=` | Retrieve saved API keys |
| `POST` | `/podcasts/jobs` | Create a new podcast generation job |
| `GET` | `/podcasts/jobs/{job_id}` | Poll job status & progress |
| `GET` | `/podcasts/jobs/{job_id}/stream` | SSE stream of turn events |
| `GET` | `/podcasts/{podcast_id}` | Get final artifact (script + audio URLs) |
| `GET` | `/podcasts/history?email=` | List all podcasts for a user |
| `GET` | `/podcasts/{podcast_id}/turns` | Get ordered turn transcript |

### Podcast Styles

`Interview` · `Debate` · `Casual Chat` · `Storytelling`

### SSE Turn Events

| Event | Payload |
|-------|---------|
| `turn_started` | `job_id`, `turn_index`, `speaker` |
| `turn_text_ready` | `turn_index`, `speaker`, `text` |
| `turn_audio_ready` | `turn_index`, `audio_chunk_url` |
| `job_completed` | `podcast_id` |
| `job_failed` | `error` |

---

## 🗄️ Database Schema

SQLite database (`resona.db`) managed by SQLAlchemy.

| Table | Purpose |
|-------|---------|
| `User` | Accounts (email/password or Google OAuth) |
| `Keys` | Per-user OpenRouter & Grok API keys |
| `Podcasts` | Podcast jobs — status, style, source URL, artifact paths |
| `PodcastTurns` | Individual turn transcript + audio chunk path |

---

## 🔧 Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python · FastAPI · Uvicorn |
| Database | SQLite · SQLAlchemy |
| LLM | OpenRouter (primary) · Grok (fallback) |
| TTS | Configured via `podcast_jobs.py` |
| Frontend | Vanilla HTML · CSS · JavaScript |
| Auth | Email/password · Google OAuth 2.0 |

---

## 📄 Planning Documents

- [Resona Plan.md](./Resona%20Plan.md) — high-level architecture and feature design
- [Resona SBS Plan.md](./Resona%20SBS%20Plan.md) — step-by-step implementation plan

---

## ⚠️ Important Notes

- `resona.db`, `storage/`, `Backend/.env`, and `logs/` are excluded from version control — see `.gitignore`
- API keys can be set globally in `.env` or per-user through the Settings page
- Background podcast jobs run **in-process** (v1) — restarting the server will interrupt any running job

---

## 📝 License

MIT — see `LICENSE` for details.
