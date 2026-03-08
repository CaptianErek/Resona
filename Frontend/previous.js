const API_BASE = "http://localhost:8000";

// ── DOM refs ────────────────────────────────────────────────────────────────────
const loadingMsg     = document.getElementById("loadingMsg");
const podcastListEl  = document.getElementById("podcastList");
const emptyStateEl   = document.getElementById("emptyState");
const detailPanel    = document.getElementById("detailPanel");
const detailTitle    = document.getElementById("detailTitle");
const detailMeta     = document.getElementById("detailMeta");
const detailTranscript = document.getElementById("detailTranscript");
const detailAudio    = document.getElementById("detailAudio");
const detailAudioInfo= document.getElementById("detailAudioInfo");
const detailDownloads= document.getElementById("detailDownloads");
const detailScriptDl = document.getElementById("detailScriptDl");
const detailAudioDl  = document.getElementById("detailAudioDl");
const backBtn        = document.getElementById("detailBack");

// ── Helpers ─────────────────────────────────────────────────────────────────────
function getCurrentUserEmail() {
    try {
        const raw = sessionStorage.getItem("currentUser");
        return raw ? (JSON.parse(raw).email || null) : null;
    } catch { return null; }
}

function formatDate(iso) {
    if (!iso) return "Unknown date";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function shortenUrl(url, max = 55) {
    if (!url) return "—";
    try { url = new URL(url).hostname + new URL(url).pathname; } catch { /* use raw */ }
    return url.length > max ? url.slice(0, max) + "…" : url;
}

// ── List rendering ───────────────────────────────────────────────────────────────
function renderCard(pod) {
    const card = document.createElement("div");
    card.className = "podcast-card";
    card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <span class="card-style-badge">${pod.style}</span>
            <span class="card-status ${pod.status}">${pod.status.replace("_", " ")}</span>
        </div>
        <div class="card-url" title="${pod.source_url}">${shortenUrl(pod.source_url)}</div>
        <div class="card-meta">
            <span>🔄 ${pod.exchanges} turns</span>
        </div>
        <div class="card-date">${formatDate(pod.created_at)}</div>
    `;
    card.addEventListener("click", () => openDetail(pod));
    return card;
}

// ── Detail panel ─────────────────────────────────────────────────────────────────
async function openDetail(pod) {
    // Populate header
    detailTitle.textContent = `${pod.style} · ${shortenUrl(pod.source_url, 40)}`;
    detailMeta.innerHTML = `
        <span>${pod.exchanges} turns</span>
        <span>${formatDate(pod.created_at)}</span>
        <span class="card-status ${pod.status}">${pod.status.replace("_", " ")}</span>
    `;

    // Downloads
    if (pod.audio_location && pod.script_location) {
        detailScriptDl.href = `${API_BASE}${pod.script_location}`;
        detailAudioDl.href  = `${API_BASE}${pod.audio_location}`;
        detailDownloads.style.display = "flex";
    } else {
        detailDownloads.style.display = "none";
    }

    // Clear transcript
    detailTranscript.innerHTML = "<p style='color:rgba(255,255,255,0.4);font-family:Average Sans;font-size:13px;'>Loading transcript…</p>";
    detailAudio.src = "";
    detailAudioInfo.textContent = "Click a turn to play its audio.";
    detailPanel.style.display = "flex";

    // Fetch turns
    try {
        const resp = await fetch(`${API_BASE}/podcasts/${pod.podcast_id}/turns`);
        const payload = await resp.json();
        if (!resp.ok || !payload.success) throw new Error(payload.error || "Failed to load turns");

        const turns = payload.data;
        detailTranscript.innerHTML = "";

        if (turns.length === 0) {
            detailTranscript.innerHTML = "<p style='color:rgba(255,255,255,0.4);font-family:Average Sans;'>No transcript available.</p>";
            return;
        }

        turns.forEach(t => {
            const row = document.createElement("div");
            row.className = "detail-turn";
            row.dataset.audioUrl = t.audio_chunk_url || "";
            row.dataset.turn = t.turn_index;
            row.innerHTML = `<span class="turn-speaker">Turn ${t.turn_index} – ${t.speaker}:</span>${t.text}`;
            row.addEventListener("click", () => playTurn(row, t));
            detailTranscript.appendChild(row);
        });
    } catch (err) {
        detailTranscript.innerHTML = `<p style='color:#ff8888;font-family:Average Sans;'>${err.message}</p>`;
    }
}

// ── Per-turn audio playback ───────────────────────────────────────────────────────
function playTurn(rowEl, turn) {
    // Deactivate all rows
    document.querySelectorAll(".detail-turn").forEach(r => r.classList.remove("active-turn"));

    if (!turn.audio_chunk_url) {
        detailAudioInfo.textContent = "No audio for this turn.";
        return;
    }

    rowEl.classList.add("active-turn");
    rowEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    detailAudioInfo.textContent = `Playing turn ${turn.turn_index} – ${turn.speaker}…`;
    detailAudio.src = `${API_BASE}${turn.audio_chunk_url}`;
    detailAudio.play().catch(() => { detailAudioInfo.textContent = "Autoplay blocked — press ▶ to play."; });

    detailAudio.onended = () => {
        rowEl.classList.remove("active-turn");
        detailAudioInfo.textContent = "Done.";

        // Auto-advance to next turn
        const nextRow = rowEl.nextElementSibling;
        if (nextRow && nextRow.classList.contains("detail-turn")) {
            const nextTurnIndex = Number(nextRow.dataset.turn);
            const allTurns = [...detailTranscript.querySelectorAll(".detail-turn")];
            const nextTurnData = { audio_chunk_url: nextRow.dataset.audioUrl, turn_index: nextTurnIndex, speaker: nextRow.querySelector(".turn-speaker").textContent.split("–")[1]?.trim() || "" };
            playTurn(nextRow, nextTurnData);
        }
    };
}

// ── Back button ───────────────────────────────────────────────────────────────────
backBtn.addEventListener("click", () => {
    detailAudio.pause();
    detailAudio.src = "";
    detailPanel.style.display = "none";
});

// ── Fetch and render history ──────────────────────────────────────────────────────
async function loadHistory() {
    const email = getCurrentUserEmail();
    if (!email) {
        loadingMsg.textContent = "Please log in to view your podcasts.";
        return;
    }

    try {
        const resp    = await fetch(`${API_BASE}/podcasts/history?email=${encodeURIComponent(email)}`);
        const payload = await resp.json();
        if (!resp.ok || !payload.success) throw new Error(payload.error || "Failed to load history");

        const podcasts = payload.data;
        loadingMsg.style.display = "none";

        if (podcasts.length === 0) {
            emptyStateEl.style.display = "flex";
            return;
        }

        podcasts.forEach(pod => {
            podcastListEl.appendChild(renderCard(pod));
        });
    } catch (err) {
        loadingMsg.textContent = `Error: ${err.message}`;
    }
}

loadHistory();
