// ─── Configuration ─────────────────────────────────────────────────────────────
const AUTH_API_BASE = "http://localhost:8000";
let GOOGLE_CLIENT_ID = "";
let configPromise = null;
let googleScriptPromise = null;
let googlePopupInFlight = false;
const GOOGLE_LIB_WAIT_TIMEOUT_MS = 5000;
const GOOGLE_LIB_WAIT_INTERVAL_MS = 50;

// Detect which auth mode this page is in:
//   "register" → new.html  (calls /new_user)
//   "login"    → login.html (calls /login)
const PAGE_MODE = document.body.dataset.authMode || "register";

// ─── Storage Keys ──────────────────────────────────────────────────────────────
let googleInitialized = false;
const DEFAULT_SIGNIN_USERS_KEY = "defaultSignInUsers";
const GOOGLE_SIGNIN_USERS_KEY = "googleSignInUsers";

// ─── Google Library Lifecycle ──────────────────────────────────────────────────
window.onGoogleLibraryLoad = function () {
  googleScriptPromise = Promise.resolve();
  initializeGoogleAuth();
};

document.addEventListener("DOMContentLoaded", async () => {
  await loadAuthConfig();
  // Warm the Google library early so first click does not race script init.
  loadGoogleLibrary().then(waitForGoogleOAuth2).catch(() => {});
  wireGoogleButton();
});

async function loadAuthConfig() {
  if (GOOGLE_CLIENT_ID) return GOOGLE_CLIENT_ID;
  if (configPromise) return configPromise;

  configPromise = fetch(`${AUTH_API_BASE}/auth/config`)
    .then((res) => res.json())
    .then((config) => {
      GOOGLE_CLIENT_ID = config?.googleClientId || "";
      return GOOGLE_CLIENT_ID;
    })
    .catch((err) => {
      console.error("Failed to load auth config:", err);
      showAuthError("Could not load Google Sign-In configuration.");
      return "";
    });

  return configPromise;
}

function initializeGoogleAuth() {
  if (googleInitialized) return;

  if (!window.google || !google.accounts || !google.accounts.id) return;

  if (!GOOGLE_CLIENT_ID) return;

  google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: handleGoogleSignIn,
    auto_select: false,
    cancel_on_tap_outside: true,
  });

  googleInitialized = true;
}

function loadGoogleLibrary() {
  if (window.google && google.accounts && google.accounts.id) {
    googleScriptPromise = Promise.resolve();
    return googleScriptPromise;
  }
  if (googleScriptPromise) return googleScriptPromise;

  googleScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-google-gsi="1"]');
    if (existing) {
      // Script tag already exists: resolve immediately if API is present,
      // otherwise wait for load/timeout.
      if (window.google?.accounts?.id) {
        resolve();
        return;
      }

      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Google script failed to load")), { once: true });

      setTimeout(() => {
        if (window.google?.accounts?.id) resolve();
      }, GOOGLE_LIB_WAIT_TIMEOUT_MS);
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.googleGsi = "1";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Google script failed to load"));
    document.head.appendChild(script);
  });

  return googleScriptPromise;
}

function waitForGoogleOAuth2(timeoutMs = GOOGLE_LIB_WAIT_TIMEOUT_MS) {
  if (window.google?.accounts?.oauth2) return Promise.resolve();

  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      if (window.google?.accounts?.oauth2) {
        resolve();
        return;
      }

      if (Date.now() - start >= timeoutMs) {
        reject(new Error("Google oauth2 API not available after script load"));
        return;
      }

      setTimeout(check, GOOGLE_LIB_WAIT_INTERVAL_MS);
    };

    check();
  });
}

function wireGoogleButton() {
  const googleBtn = document.getElementById("google-logo");
  if (!googleBtn) {
    console.warn("auth.js: #google-logo element not found.");
    return;
  }

  if (googleBtn.dataset.wired === "true") return;

  googleBtn.style.cursor = "pointer";
  googleBtn.addEventListener("click", triggerGooglePopup);
  googleBtn.dataset.wired = "true";
}

async function triggerGooglePopup() {
  if (googlePopupInFlight) return;
  googlePopupInFlight = true;

  try {
    await loadGoogleLibrary();
    await waitForGoogleOAuth2();
  } catch (err) {
    console.error("Failed to load Google library:", err);
    showAuthError("Google sign-in library failed to load.");
    googlePopupInFlight = false;
    return;
  }

  if (!GOOGLE_CLIENT_ID) {
    await loadAuthConfig();
  }

  if (!GOOGLE_CLIENT_ID) {
    showAuthError("Google Client ID missing. Set GOOGLE_CLIENT_ID on backend.");
    googlePopupInFlight = false;
    return;
  }

  if (!window.google || !google.accounts || !google.accounts.oauth2) {
    showAuthError("Google sign-in library not loaded yet. Please retry.");
    googlePopupInFlight = false;
    return;
  }

  initializeGoogleAuth();

  const tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: GOOGLE_CLIENT_ID,
    scope: "openid email profile",
    callback: (tokenResponse) => {
      googlePopupInFlight = false;
      if (tokenResponse.error) {
        console.error("Google sign-in error:", tokenResponse.error);
        showAuthError("Google sign-in failed. Please try again.");
        return;
      }
      fetchGoogleUserProfile(tokenResponse.access_token);
    },
  });

  tokenClient.requestAccessToken({ prompt: "" });
}

/**
 * Called when Google One-Tap returns a credential JWT.
 * @param {google.accounts.id.CredentialResponse} response
 */
function handleGoogleSignIn(response) {
  if (!response.credential) {
    showAuthError("Google sign-in was cancelled.");
    return;
  }
  const userInfo = parseJwt(response.credential);
  // userInfo.sub is the stable Google user ID — used as provider_id
  callBackendWithGoogle(userInfo);
}

/**
 * Called after fetching the userinfo endpoint with an OAuth2 access token.
 * @param {string} accessToken
 */
function fetchGoogleUserProfile(accessToken) {
  fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
    .then((res) => res.json())
    .then((userInfo) => callBackendWithGoogle(userInfo))
    .catch((err) => {
      console.error("Failed to fetch user profile:", err);
      showAuthError("Could not retrieve your profile. Please try again.");
    });
}

/**
 * Calls either /new_user or /login on the backend with Google credentials.
 * Google sign-in does NOT send a password; it sends provider_id (the Google sub).
 *
 * @param {{ name: string, email: string, sub: string, picture?: string }} userInfo
 */
async function callBackendWithGoogle(userInfo) {
  if (!userInfo.email || !userInfo.sub) {
    showAuthError("Incomplete profile received from Google. Please try again.");
    return;
  }

  const endpoint = PAGE_MODE === "login" ? "/login" : "/new_user";
  const payload = {
    name: userInfo.name || userInfo.email,
    email: userInfo.email,
    provider: "google",
    provider_id: userInfo.sub, // required for google; password is NOT sent
  };

  showAuthMessage("Connecting with Google…", "#aaaaaa");

  try {
    const response = await fetch(`${AUTH_API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (response.ok && data.success) {
      // Persist lightweight session data
      sessionStorage.setItem(
        "currentUser",
        JSON.stringify({
          name: data.data.name,
          email: data.data.email,
          provider: "google",
          picture: userInfo.picture || "",
        })
      );
      saveGoogleSignInUser(userInfo);
      showAuthSuccess(`Welcome, ${data.data.name}! Redirecting…`);
      setTimeout(() => {
        window.location.href = "./studio.html";
      }, 1200);
    } else {
      // If registering and user already exists, try logging in automatically
      if (PAGE_MODE === "register" && response.status === 409) {
        showAuthMessage("Account exists, signing you in…", "#aaaaaa");
        return loginExistingGoogleUser(payload, userInfo);
      }
      showAuthError(data.error || "Authentication failed. Please try again.");
    }
  } catch (err) {
    console.error("Backend call error:", err);
    showAuthError("Could not reach the server. Make sure the backend is running.");
  }
}

/**
 * Fallback: if /new_user returns 409 (already exists) during registration,
 * call /login so the user doesn't have to switch pages.
 */
async function loginExistingGoogleUser(payload, userInfo) {
  try {
    const response = await fetch(`${AUTH_API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (response.ok && data.success) {
      sessionStorage.setItem(
        "currentUser",
        JSON.stringify({
          name: data.data.name,
          email: data.data.email,
          provider: "google",
          picture: userInfo.picture || "",
        })
      );
      saveGoogleSignInUser(userInfo);
      showAuthSuccess(`Welcome back, ${data.data.name}! Redirecting…`);
      setTimeout(() => {
        window.location.href = "./studio.html";
      }, 1200);
    } else {
      showAuthError(data.error || "Sign-in failed. Please try again.");
    }
  } catch (err) {
    console.error("Login fallback error:", err);
    showAuthError("Could not reach the server. Make sure the backend is running.");
  }
}

// ─── Storage Helpers ───────────────────────────────────────────────────────────

function getDefaultSignInUsers() {
  return readStorageArray(DEFAULT_SIGNIN_USERS_KEY)
    .map((user) => ({
      name: typeof user?.name === "string" ? user.name : "",
      email: typeof user?.email === "string" ? user.email : "",
      password: typeof user?.password === "string" ? user.password : "",
    }))
    .filter((user) => user.name && user.email && user.password);
}

function getGoogleSignInEmails() {
  const users = readStorageArray(GOOGLE_SIGNIN_USERS_KEY);
  const storedEmails = users
    .map((user) => (typeof user?.email === "string" ? user.email : ""))
    .filter(Boolean);

  const currentGoogleUser = readStorageObject(sessionStorage, "currentUser");
  if (
    currentGoogleUser?.provider === "google" &&
    typeof currentGoogleUser?.email === "string" &&
    currentGoogleUser.email
  ) {
    storedEmails.push(currentGoogleUser.email);
  }

  return [...new Set(storedEmails)];
}

function saveGoogleSignInUser(userInfo) {
  const users = readStorageArray(GOOGLE_SIGNIN_USERS_KEY);
  users.push({
    name: userInfo?.name || "",
    email: userInfo?.email || "",
    picture: userInfo?.picture || "",
  });
  localStorage.setItem(GOOGLE_SIGNIN_USERS_KEY, JSON.stringify(users));
}

function readStorageArray(key) {
  try {
    const value = localStorage.getItem(key);
    if (!value) return [];
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function readStorageObject(storage, key) {
  try {
    const value = storage.getItem(key);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

window.getDefaultSignInUsers = getDefaultSignInUsers;
window.getGoogleSignInEmails = getGoogleSignInEmails;

// ─── JWT Parser ────────────────────────────────────────────────────────────────

/**
 * @param {string} token
 * @returns {object}
 */
function parseJwt(token) {
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch (e) {
    console.error("Failed to parse JWT:", e);
    return {};
  }
}

// ─── UI Feedback ───────────────────────────────────────────────────────────────

function showAuthError(message) {
  showAuthMessage(message, "#ff4444");
}

function showAuthSuccess(message) {
  showAuthMessage(message, "#44cc88");
}

function showAuthMessage(message, color) {
  let msgEl = document.getElementById("google-auth-message");
  if (!msgEl) {
    msgEl = document.createElement("p");
    msgEl.id = "google-auth-message";
    msgEl.style.cssText =
      "text-align:center;font-family:'Inria Serif',serif;" +
      "font-size:14px;margin-top:10px;transition:opacity 0.3s;";
    const googleBtn = document.querySelector(".google-button");
    if (googleBtn) {
      googleBtn.insertAdjacentElement("afterend", msgEl);
    } else {
      document.body.appendChild(msgEl);
    }
  }
  msgEl.style.color = color;
  msgEl.textContent = message;
  msgEl.style.opacity = "1";
}
