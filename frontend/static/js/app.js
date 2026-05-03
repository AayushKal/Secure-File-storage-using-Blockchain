/**
 * app.js — ChainVault (Render-compatible)
 *
 * No WebSocket. The frontend polls /api/chain every 5 seconds.
 * Browser-side chain validation fetches the chain on demand over HTTPS.
 * Everything else is identical to the original.
 */

/* ================================================================
   Session state
   ================================================================ */
let currentUser = null;

async function initSession() {
  try {
    const res = await fetch("/api/auth/me", { credentials: "include" });
    if (!res.ok) { window.location.href = "/login"; return; }
    currentUser = await res.json();

    const roleTag = currentUser.role === "admin"
      ? ' <span class="badge badge-admin">admin</span>' : "";
    document.getElementById("user-display").innerHTML =
      `${currentUser.username}${roleTag}`;

    document.getElementById("upload-as").textContent = currentUser.username;

    document.getElementById("files-scope-note").textContent =
      currentUser.role === "admin"
        ? "Showing all files on the blockchain (admin view)."
        : "Showing files you own or have access to.";

  } catch {
    window.location.href = "/login";
  }
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  window.location.href = "/login";
}


/* ================================================================
   Chain polling — replaces WebSocket
   Calls /api/chain every 5 seconds and updates the status bar.
   ================================================================ */
let _pollTimer = null;

async function pollChain() {
  try {
    const res  = await fetch("/api/chain", { credentials: "include" });
    if (!res.ok) return;
    const data = await res.json();

    // Update status bar
    document.getElementById("status-blocks").textContent = data.length;
    const validEl = document.getElementById("status-valid");
    validEl.textContent  = data.is_valid ? "✓ valid" : "✗ invalid";
    validEl.style.color  = data.is_valid ? "var(--accent2)" : "var(--danger)";

    // Keep BrowserChain in sync for client-side validation
    if (data.blocks && data.blocks.length) {
      await BrowserChain.syncChain(data.blocks);
    }

    // Refresh file list if that tab is open
    const filesPanel = document.getElementById("tab-files");
    if (filesPanel && filesPanel.classList.contains("active")) {
      loadFiles();
    }

  } catch {
    // Server asleep or network error — show disconnected quietly
    document.getElementById("status-valid").textContent = "—";
  }
}

function startPolling() {
  pollChain();                            // immediate first call
  _pollTimer = setInterval(pollChain, 5000);
}


/* ================================================================
   UI helpers
   ================================================================ */
function show(id, html, type = "info") {
  const el = document.getElementById(id);
  el.className = `result result-${type}`;
  el.innerHTML = html;
}

function fmt(obj) {
  return Object.entries(obj).map(([k, v]) => {
    const val      = typeof v === "object" ? JSON.stringify(v) : String(v);
    const copyable = val.length > 20
      ? `${val} <button class="copy-btn" onclick="copyText('${val}')">copy</button>`
      : val;
    return `<b>${k}:</b> ${copyable}`;
  }).join("<br>");
}

function copyText(text) {
  navigator.clipboard.writeText(text);
}

function showTab(name) {
  const names = ["upload", "manage", "verify", "history", "files"];
  document.querySelectorAll(".tab").forEach((t, i) => {
    t.classList.toggle("active", names[i] === name);
  });
  document.querySelectorAll(".tab-panel").forEach(p => {
    p.classList.toggle("active", p.id === `tab-${name}`);
  });
  if (name === "files") loadFiles();
}


/* ================================================================
   API calls
   ================================================================ */

/* ── Upload ─────────────────────────────────────────────────── */
async function uploadFile() {
  const file = document.getElementById("up-file").files[0];
  if (!file) return show("up-result", "Please select a file.", "err");

  const btn = document.getElementById("up-btn");
  btn.disabled    = true;
  btn.innerHTML   = '<span class="loading"></span> Uploading…';

  const form = new FormData();
  form.append("file", file);

  try {
    const res  = await fetch("/api/upload", {
      method: "POST", body: form, credentials: "include",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);

    show("up-result",
      `Upload successful!<br><br>${fmt({
        file_id:   data.file_id,
        cid:       data.cid,
        file_hash: data.file_hash,
        block:     `#${data.block_index}`,
      })}<br><br><b style="color:var(--warn)">
        ⚠ Save the file_id and file_hash — you need them to verify and share.
      </b>`, "ok");

    pollChain();   // refresh status bar immediately after upload

  } catch (e) {
    show("up-result", e.message, "err");
  } finally {
    btn.disabled  = false;
    btn.textContent = "Upload & Register on Chain";
  }
}

/* ── Grant ──────────────────────────────────────────────────── */
async function grantAccess() {
  const file_id  = document.getElementById("gr-file-id").value.trim();
  const new_user = document.getElementById("gr-user").value.trim();
  if (!file_id || !new_user)
    return show("gr-result", "All fields are required.", "err");
  try {
    const res  = await fetch("/api/grant", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id, new_user }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    show("gr-result",
      `Access granted to <b>${new_user}</b>.<br>Access list: ${data.access_list.join(", ")}`,
      "ok");
  } catch (e) { show("gr-result", e.message, "err"); }
}

/* ── Revoke ─────────────────────────────────────────────────── */
async function revokeAccess() {
  const file_id     = document.getElementById("rv-file-id").value.trim();
  const target_user = document.getElementById("rv-user").value.trim();
  if (!file_id || !target_user)
    return show("rv-result", "All fields are required.", "err");
  try {
    const res  = await fetch("/api/revoke", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id, target_user }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    show("rv-result",
      `Access revoked from <b>${target_user}</b>.<br>Access list: ${data.access_list.join(", ")}`,
      "ok");
  } catch (e) { show("rv-result", e.message, "err"); }
}

/* ── Download ───────────────────────────────────────────────── */
async function downloadFile() {
  const file_id = document.getElementById("dl-file-id").value.trim();
  if (!file_id) return show("dl-result", "File ID is required.", "err");
  try {
    const res = await fetch(`/api/download/${file_id}`, { credentials: "include" });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.error);
    }
    const cd        = res.headers.get("Content-Disposition") || "";
    const nameMatch = cd.match(/filename="?([^"]+)"?/);
    const filename  = nameMatch ? nameMatch[1] : file_id;

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    show("dl-result", `Downloaded and decrypted: <b>${filename}</b>`, "ok");
  } catch (e) { show("dl-result", e.message, "err"); }
}

/* ── Verify (server-side hash comparison) ───────────────────── */
async function verifyFile() {
  const file_id   = document.getElementById("vf-file-id").value.trim();
  const file_hash = document.getElementById("vf-hash").value.trim();
  if (!file_id || !file_hash)
    return show("vf-result", "Both fields are required.", "err");
  try {
    const res  = await fetch(`/api/verify/${file_id}/${file_hash}`,
                             { credentials: "include" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    show("vf-result",
      data.is_valid
        ? "✓ Integrity verified — this file has NOT been tampered with."
        : `✗ Integrity FAILED — the file may have been modified.<br>Stored hash: ${data.stored_hash}`,
      data.is_valid ? "ok" : "err");
  } catch (e) { show("vf-result", e.message, "err"); }
}

/* ── Browser-side chain validation ─────────────────────────── */
async function validateChain() {
  const btn = document.getElementById("cv-btn");
  btn.disabled   = true;
  btn.textContent = "Fetching chain…";

  try {
    // Always fetch a fresh copy — no dependency on WebSocket
    const res  = await fetch("/api/chain", { credentials: "include" });
    const data = await res.json();
    if (!res.ok) throw new Error("Could not fetch chain");

    const chain = data.blocks || [];
    if (!chain.length) {
      show("cv-result", "Chain is empty.", "info"); return;
    }

    btn.textContent = "Validating…";
    const valid = await BrowserChain.validateChain(chain);

    show("cv-result",
      valid
        ? `✓ Your browser independently validated all ${chain.length} blocks.<br>
           Every SHA-256 hash matches. Every chain link is intact.`
        : "✗ Chain validation FAILED — one or more blocks are invalid.",
      valid ? "ok" : "err");

  } catch (e) {
    show("cv-result", e.message, "err");
  } finally {
    btn.disabled   = false;
    btn.textContent = "Run Browser Validation";
  }
}

/* ── History ────────────────────────────────────────────────── */
async function getHistory() {
  const file_id = document.getElementById("hi-file-id").value.trim();
  if (!file_id) return show("hi-result", "File ID is required.", "err");
  try {
    const res    = await fetch(`/api/history/${file_id}`, { credentials: "include" });
    const blocks = await res.json();
    if (!res.ok) throw new Error(blocks.error);
    if (!blocks.length) { show("hi-result", "No history found.", "info"); return; }

    const html = `<div class="timeline">` +
      blocks.map(b => {
        const d    = b.data || {};
        const type = (d.type || "BLOCK").replace(/_/g, " ");
        const ts   = new Date(
          d.uploaded_at || d.updated_at || (b.timestamp * 1000)
        ).toLocaleString();
        return `<div class="timeline-item">
          <div>
            <div class="t-type">${type}</div>
            <div class="t-meta">${ts}</div>
            ${d.access_list
              ? `<div class="t-meta">Access: ${d.access_list.join(", ")}</div>` : ""}
            <div class="t-meta" style="font-size:.6rem;margin-top:.2rem">${b.hash}</div>
          </div>
        </div>`;
      }).join("") + `</div>`;

    show("hi-result", html, "info");
  } catch (e) { show("hi-result", e.message, "err"); }
}

/* ── All files ──────────────────────────────────────────────── */
async function loadFiles() {
  try {
    const res   = await fetch("/api/files", { credentials: "include" });
    const files = await res.json();
    const grid  = document.getElementById("file-grid");

    if (!files.length) {
      grid.innerHTML = `<div class="empty">No files yet</div>`; return;
    }

    grid.innerHTML = files.map(f => `
      <div class="file-card">
        <div class="file-name">
          ${f.filename || "Unknown"}
          <span class="badge ${f.is_deleted ? "badge-deleted" : "badge-active"}">
            ${f.is_deleted ? "deleted" : "active"}
          </span>
        </div>
        <div class="file-id-text">
          ${f.file_id}
          <button class="copy-btn" onclick="copyText('${f.file_id}')">copy id</button>
        </div>
        <div class="file-meta">
          <span>Owner: ${f.owner}</span>
          <span>Access: ${(f.access_list || []).join(", ") || "none"}</span>
          <span>${new Date(f.uploaded_at).toLocaleDateString()}</span>
        </div>
      </div>`).join("");
  } catch (e) {
    document.getElementById("file-grid").innerHTML =
      `<div class="empty" style="color:var(--danger)">${e.message}</div>`;
  }
}


/* ================================================================
   Boot
   ================================================================ */
initSession();
startPolling();
loadFiles();
