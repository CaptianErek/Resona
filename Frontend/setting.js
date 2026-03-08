// ─── Configuration ───────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";

// ─── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadUserProfile();
    wireAvatarUpload();
    wireKeyForms();
    fetchSavedKeys();
});

// ─── Profile ─────────────────────────────────────────────────────────────────

function loadUserProfile() {
    const user = readSession("currentUser");

    const nameEl  = document.getElementById("user-name");
    const emailEl = document.getElementById("user-email");
    const imgEl   = document.getElementById("profile-img");

    if (!user) {
        if (nameEl)  nameEl.textContent  = "Guest";
        if (emailEl) emailEl.textContent = "";
        return;
    }

    if (nameEl)  nameEl.textContent  = user.name  || "Unknown";
    if (emailEl) emailEl.textContent = user.email || "";

    // Restore saved avatar (stored per-email in localStorage)
    if (user.email) {
        const savedAvatar = localStorage.getItem(`avatar_${user.email}`);
        if (savedAvatar && imgEl) {
            imgEl.src = savedAvatar;
        } else if (user.picture && imgEl) {
            imgEl.src = user.picture;
        }
    }
}

// ─── Avatar Upload ────────────────────────────────────────────────────────────

function wireAvatarUpload() {
    const wrapper   = document.getElementById("avatar-wrapper");
    const fileInput = document.getElementById("avatar-file-input");
    const imgEl     = document.getElementById("profile-img");

    if (!wrapper || !fileInput || !imgEl) return;

    wrapper.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        const file = fileInput.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            const dataUrl = e.target.result;
            imgEl.src = dataUrl;

            // Persist avatar per user email
            const user = readSession("currentUser");
            if (user?.email) {
                localStorage.setItem(`avatar_${user.email}`, dataUrl);
            }
        };
        reader.readAsDataURL(file);
    });
}

// ─── API Keys ─────────────────────────────────────────────────────────────────

function wireKeyForms() {
    const groqForm       = document.getElementById("groq-form");
    const openrouterForm = document.getElementById("openrouter-form");

    if (groqForm) {
        groqForm.addEventListener("submit", (e) => {
            e.preventDefault();
            const key = document.getElementById("groq-input")?.value?.trim();
            if (key) saveKey("grok", key, "groq-status");
        });
    }

    if (openrouterForm) {
        openrouterForm.addEventListener("submit", (e) => {
            e.preventDefault();
            const key = document.getElementById("openrouter-input")?.value?.trim();
            if (key) saveKey("openrouter", key, "openrouter-status");
        });
    }
}

async function saveKey(keyType, keyValue, statusId) {
    const user = readSession("currentUser");
    if (!user?.email) {
        setStatus(statusId, "Not logged in — please log in first.", "#ff4444");
        return;
    }

    setStatus(statusId, "Saving…", "#aaaaaa");

    try {
        const response = await fetch(`${API_BASE}/settings/keys`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                useremail:     user.email,
                key_type:      keyType,   // "grok" | "openrouter"
                key_value:     keyValue,
            }),
        });

        const data = await response.json();

        if (response.ok && data.success) {
            setStatus(statusId, "✓ Saved successfully!", "#44cc88");
        } else {
            setStatus(statusId, data.error || "Failed to save key.", "#ff4444");
        }
    } catch (err) {
        console.error("saveKey error:", err);
        setStatus(statusId, "Could not reach server.", "#ff4444");
    }
}

async function fetchSavedKeys() {
    const user = readSession("currentUser");
    if (!user?.email) return;

    try {
        const response = await fetch(
            `${API_BASE}/settings/keys?email=${encodeURIComponent(user.email)}`
        );
        if (!response.ok) return;

        const data = await response.json();
        if (!data.success) return;

        const groqInput       = document.getElementById("groq-input");
        const openrouterInput = document.getElementById("openrouter-input");

        // Show masked keys so user knows they're already set
        if (data.data.grokApi && groqInput) {
            groqInput.value       = maskKey(data.data.grokApi);
            groqInput.dataset.real = data.data.grokApi;
            groqInput.addEventListener("focus", unmaskField, { once: true });
        }
        if (data.data.openrouterApi && openrouterInput) {
            openrouterInput.value       = maskKey(data.data.openrouterApi);
            openrouterInput.dataset.real = data.data.openrouterApi;
            openrouterInput.addEventListener("focus", unmaskField, { once: true });
        }
    } catch (_) {
        // Silently ignore — keys just won't be pre-filled
    }
}

function unmaskField(e) {
    const input = e.target;
    if (input.dataset.real) {
        input.value = input.dataset.real;
    }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function maskKey(key) {
    if (!key || key.length < 8) return key;
    return key.slice(0, 4) + "••••••••" + key.slice(-4);
}

function setStatus(elementId, message, color) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.textContent = message;
    el.style.color = color;
}

function readSession(key) {
    try {
        const value = sessionStorage.getItem(key);
        return value ? JSON.parse(value) : null;
    } catch {
        return null;
    }
}
