const nameInput = document.getElementById("name");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const submitButton = document.querySelector("button[type='submit']");
const form = document.querySelector(".form");

const API_BASE = "http://localhost:8000";

function checkFormValidity() {
    return (
        nameInput.checkValidity() &&
        emailInput.checkValidity() &&
        passwordInput.checkValidity()
    );
}

function updateButton() {
    submitButton.disabled = !checkFormValidity();
}

submitButton.disabled = true;

nameInput.addEventListener("input", updateButton);
emailInput.addEventListener("input", updateButton);
passwordInput.addEventListener("input", updateButton);

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!checkFormValidity()) return;

    submitButton.disabled = true;
    submitButton.textContent = "Signing in…";

    try {
        const response = await fetch(`${API_BASE}/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: nameInput.value.trim(),
                email: emailInput.value.trim(),
                password: passwordInput.value,
                provider: "default"
                // provider_id is NOT sent for default provider
            }),
        });

        const data = await response.json();

        if (response.ok && data.success) {
            sessionStorage.setItem("currentUser", JSON.stringify(data.data));
            window.location.href = "./studio.html";
        } else {
            showFormError(data.error || "Login failed. Please check your credentials.");
            submitButton.disabled = false;
            submitButton.textContent = "Sign In";
        }
    } catch (err) {
        console.error("Login error:", err);
        showFormError("Could not reach the server. Make sure the backend is running.");
        submitButton.disabled = false;
        submitButton.textContent = "Sign In";
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
