const API_BASE = "http://localhost:8000";

const blogForm = document.getElementById("blogForm");
const blogUrlInput = document.getElementById("blogUrlInput");
const urlSubmitBtn = document.getElementById("urlSubmitBtn");
const exchangesInput = document.getElementById("exchangesInput");
const styleOptions = document.querySelectorAll(".option");
const generateButton = document.getElementById("generateButton");

const urlError = document.getElementById("urlError");
const exchangesError = document.getElementById("exchangesError");
const submitError = document.getElementById("submitError");

let isUrlSubmitted = false;
let selectedStyle = null;

function exchangesValid() {
    const value = Number(exchangesInput.value);
    return Number.isInteger(value) && value >= 2 && value <= 40;
}

function updateGenerateButton() {
    const canGenerate = isUrlSubmitted && selectedStyle && exchangesValid();
    generateButton.disabled = !canGenerate;
    generateButton.style.cursor = canGenerate ? "pointer" : "not-allowed";
    generateButton.style.opacity = canGenerate ? "1" : "0.5";
}

function getCurrentUserEmail() {
    const raw = sessionStorage.getItem("currentUser");
    if (!raw) return null;

    try {
        const parsed = JSON.parse(raw);
        return parsed.email || null;
    } catch {
        return null;
    }
}

blogForm.addEventListener("submit", (e) => {
    e.preventDefault();

    if (blogUrlInput.checkValidity() && blogUrlInput.value.trim() !== "") {
        isUrlSubmitted = true;
        urlSubmitBtn.textContent = "Submitted";
        urlSubmitBtn.style.backgroundColor = "#4CAF50";
        urlError.style.display = "none";
        submitError.textContent = "";
        updateGenerateButton();
        return;
    }

    urlError.style.display = "block";
});

blogUrlInput.addEventListener("input", () => {
    urlError.style.display = "none";
    submitError.textContent = "";

    if (isUrlSubmitted) {
        isUrlSubmitted = false;
        urlSubmitBtn.textContent = "Submit";
        urlSubmitBtn.style.backgroundColor = "";
        updateGenerateButton();
    }
});

exchangesInput.addEventListener("input", () => {
    if (!exchangesValid()) {
        exchangesError.style.display = "block";
    } else {
        exchangesError.style.display = "none";
    }
    submitError.textContent = "";
    updateGenerateButton();
});

styleOptions.forEach((option) => {
    option.addEventListener("click", () => {
        styleOptions.forEach((opt) => opt.classList.remove("selected"));
        option.classList.add("selected");
        selectedStyle = option.dataset.style;
        submitError.textContent = "";
        updateGenerateButton();
    });
});

generateButton.addEventListener("click", async () => {
    if (!(isUrlSubmitted && selectedStyle && exchangesValid())) {
        return;
    }

    const email = getCurrentUserEmail();
    if (!email) {
        submitError.textContent = "Please log in again before generating.";
        return;
    }

    generateButton.disabled = true;
    generateButton.textContent = "Creating job...";
    submitError.textContent = "";

    try {
        const response = await fetch(`${API_BASE}/podcasts/jobs`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: blogUrlInput.value.trim(),
                style: selectedStyle,
                exchanges: Number(exchangesInput.value),
                user_email: email,
            }),
        });

        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || "Failed to create job");
        }

        const jobId = payload.data.job_id;
        window.location.href = `./generated.html?job_id=${encodeURIComponent(jobId)}`;
    } catch (error) {
        submitError.textContent = error.message || "Failed to create podcast job.";
        generateButton.disabled = false;
        generateButton.textContent = "Generate Podcast";
    }
});

updateGenerateButton();
