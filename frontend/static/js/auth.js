/* auth.js — shared logic for login.html and register.html */

function showError(msg) {
  const box = document.getElementById("error-box");
  box.textContent = msg;
  box.style.display = "block";
}

function hideError() {
  const box = document.getElementById("error-box");
  if (box) box.style.display = "none";
}

async function authRequest(url, body, redirectTo) {
  hideError();

  // Disable the button to prevent double-submit
  const btn = document.querySelector(".btn-auth");
  if (btn) { btn.disabled = true; btn.textContent = "Please wait…"; }

  try {
    const res  = await fetch(url, {
      method:      "POST",
      headers:     { "Content-Type": "application/json" },
      credentials: "include",
      body:        JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "Something went wrong.");
      return;
    }

    // Success — redirect
    window.location.href = redirectTo;

  } catch (e) {
    showError("Could not reach the server. Is it running?");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || "Submit"; }
  }
}
