const nameInput = document.getElementById("name");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const confirmPasswordInput = document.getElementById("confirm-password");
const submitButton = document.getElementById("submit-btn");
const form = document.querySelector(".form");

const API_BASE = "http://localhost:8000";

function checkPassword() {
    const error = document.getElementById("password-error");
    if (!passwordInput.validity.patternMismatch) {
        error.textContent = "";
    } else {
        error.textContent = "Must contain at least 8 characters, including uppercase, lowercase, number and special character";
    }
}

function checkPasswordMatch() {
    const passwordError = document.getElementById("confirm-password-error");
    if (passwordInput.value !== confirmPasswordInput.value) {
        passwordError.textContent = "Passwords do not match";
    } else {
        passwordError.textContent = "";
    }
}

function checkFormValidity() {
    return (
        nameInput.checkValidity() &&
        emailInput.checkValidity() &&
        passwordInput.checkValidity() &&
        !passwordInput.validity.patternMismatch &&
        confirmPasswordInput.checkValidity() &&
        passwordInput.value === confirmPasswordInput.value
    );
}

function updateButton() {
    submitButton.disabled = !checkFormValidity();
}

submitButton.disabled = true;

nameInput.addEventListener("input", updateButton);
emailInput.addEventListener("input", updateButton);

passwordInput.addEventListener("input", () => {
    checkPassword();
    updateButton();
});

confirmPasswordInput.addEventListener("input", () => {
    checkPasswordMatch();
    updateButton();
});

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!checkFormValidity()) return;

    submitButton.disabled = true;
    submitButton.textContent = "Creating account…";

    try {
        const response = await fetch(`${API_BASE}/new_user`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: nameInput.value.trim(),
                email: emailInput.value.trim(),
                password: passwordInput.value,
                provider: "default"
                // provider_id is NOT sent for default — the backend doesn't need it
            }),
        });

        const data = await response.json();

        if (response.ok && data.success) {
            // Store basic session info and redirect
            sessionStorage.setItem("currentUser", JSON.stringify(data.data));
            window.location.href = "./studio.html";
        } else {
            showFormError(data.error || "Registration failed. Please try again.");
            submitButton.disabled = false;
            submitButton.textContent = "Create your voice";
        }
    } catch (err) {
        console.error("Registration error:", err);
        showFormError("Could not reach the server. Make sure the backend is running.");
        submitButton.disabled = false;
        submitButton.textContent = "Create your voice";
    }
});

function showFormError(message) {
    let el = document.getElementById("form-error-message");
    if (!el) {
        el = document.createElement("p");
        el.id = "form-error-message";
        el.style.cssText =
            "color:#ff4444;text-align:center;font-size:14px;margin-top:10px;";
        form.insertAdjacentElement("afterend", el);
    }
    el.textContent = message;
}