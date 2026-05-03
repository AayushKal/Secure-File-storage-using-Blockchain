"""
ChainVault — Main server (Render-compatible)
  - Flask REST API, single process, single port
  - No WebSocket — frontend polls /api/chain every 5 seconds instead
  - MongoDB Atlas for both user accounts and blockchain persistence
  - Session-based auth with role-based access
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, Response, jsonify, redirect,
                   request, send_from_directory, session)
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from api.auth import get_user, login_user, register_user, user_exists
from blockchain.chain import Blockchain
from storage.ipfs import (decrypt_file, encrypt_file,
                           hash_file, upload_to_ipfs, download_from_ipfs)

load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
)
app.secret_key = os.getenv("SECRET_KEY", "change-this-in-production")
CORS(app, supports_credentials=True)

bc = Blockchain()


# ── Auth helpers ──────────────────────────────────────────────────────────────
def current_user() -> dict | None:
    username = session.get("username")
    if not username:
        return None
    return {"username": username, "role": session.get("role", "user")}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Not authenticated"}), 401
        if user["role"] != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Page routes ───────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return send_from_directory("../frontend", "index.html")


@app.route("/login")
def login_page():
    if current_user():
        return redirect("/")
    return send_from_directory("../frontend", "login.html")


@app.route("/register")
def register_page():
    if current_user():
        return redirect("/")
    return send_from_directory("../frontend", "register.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("../frontend/static", filename)


# ── Auth API ──────────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
def api_register():
    body     = request.get_json() or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    role     = "admin" if not user_exists() else "user"
    try:
        user = register_user(username, password, role)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    session["username"] = user["username"]
    session["role"]     = user["role"]
    return jsonify({"success": True, "username": user["username"],
                    "role": user["role"]})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    body     = request.get_json() or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    user     = login_user(username, password)
    if not user:
        return jsonify({"error": "Invalid username or password"}), 401
    session["username"] = user["username"]
    session["role"]     = user["role"]
    return jsonify({"success": True, "username": user["username"],
                    "role": user["role"]})


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    user = current_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify(user)


# ── File API ──────────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    user = current_user()
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file      = request.files["file"]
    raw_bytes = file.read()
    file_hash = hash_file(raw_bytes)
    encrypted = encrypt_file(raw_bytes)
    cid       = upload_to_ipfs(encrypted, file.filename)
    file_id   = str(uuid.uuid4())

    record = {
        "type":        "FILE_UPLOAD",
        "file_id":     file_id,
        "filename":    file.filename,
        "cid":         cid,
        "file_hash":   file_hash,
        "owner":       user["username"],
        "access_list": [user["username"]],
        "is_deleted":  False,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    block = bc.add_record(record)

    return jsonify({
        "success":     True,
        "file_id":     file_id,
        "cid":         cid,
        "file_hash":   file_hash,
        "block_index": block.index,
    })


@app.route("/api/file/<file_id>", methods=["GET"])
@login_required
def get_file(file_id):
    user   = current_user()
    record = bc.get_file(file_id)
    if not record:
        return jsonify({"error": "File not found"}), 404
    if user["role"] != "admin":
        if user["username"] not in record.get("access_list", []):
            return jsonify({"error": "Access denied"}), 403
    return jsonify(record)


@app.route("/api/download/<file_id>", methods=["GET"])
@login_required
def download(file_id):
    user   = current_user()
    record = bc.get_file(file_id)
    if not record:
        return jsonify({"error": "File not found"}), 404
    if record.get("is_deleted"):
        return jsonify({"error": "File has been deleted"}), 410
    if user["role"] != "admin":
        if user["username"] not in record.get("access_list", []):
            return jsonify({"error": "Access denied"}), 403

    encrypted = download_from_ipfs(record["cid"])
    raw_bytes = decrypt_file(encrypted)
    return Response(
        raw_bytes,
        mimetype="application/octet-stream",
        headers={"Content-Disposition":
                 f'attachment; filename="{record["filename"]}"'},
    )


@app.route("/api/grant", methods=["POST"])
@login_required
def grant():
    user          = current_user()
    body          = request.get_json() or {}
    file_id       = body.get("file_id", "").strip()
    new_user_name = body.get("new_user", "").strip()

    if not file_id or not new_user_name:
        return jsonify({"error": "file_id and new_user are required"}), 400

    record = bc.get_file(file_id)
    if not record:
        return jsonify({"error": "File not found"}), 404
    if record["owner"] != user["username"] and user["role"] != "admin":
        return jsonify({"error": "Only the owner can grant access"}), 403
    if record.get("is_deleted"):
        return jsonify({"error": "File is deleted"}), 410
    if new_user_name in record["access_list"]:
        return jsonify({"error": f"{new_user_name} already has access"}), 400
    if not get_user(new_user_name):
        return jsonify({"error": f"User '{new_user_name}' does not exist"}), 404

    updated = {
        **record,
        "type":        "ACCESS_GRANT",
        "access_list": record["access_list"] + [new_user_name],
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }
    bc.add_record(updated)
    return jsonify({"success": True, "access_list": updated["access_list"]})


@app.route("/api/revoke", methods=["POST"])
@login_required
def revoke():
    user        = current_user()
    body        = request.get_json() or {}
    file_id     = body.get("file_id", "").strip()
    target_user = body.get("target_user", "").strip()

    if not file_id or not target_user:
        return jsonify({"error": "file_id and target_user are required"}), 400

    record = bc.get_file(file_id)
    if not record:
        return jsonify({"error": "File not found"}), 404
    if record["owner"] != user["username"] and user["role"] != "admin":
        return jsonify({"error": "Only the owner can revoke access"}), 403
    if target_user == record["owner"]:
        return jsonify({"error": "Cannot revoke owner's own access"}), 400
    if target_user not in record["access_list"]:
        return jsonify({"error": f"{target_user} does not have access"}), 400

    updated = {
        **record,
        "type":        "ACCESS_REVOKE",
        "access_list": [u for u in record["access_list"] if u != target_user],
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }
    bc.add_record(updated)
    return jsonify({"success": True, "access_list": updated["access_list"]})


@app.route("/api/verify/<file_id>/<file_hash>", methods=["GET"])
@login_required
def verify(file_id, file_hash):
    record = bc.get_file(file_id)
    if not record:
        return jsonify({"error": "File not found"}), 404
    return jsonify({
        "is_valid":    record["file_hash"] == file_hash,
        "stored_hash": record["file_hash"],
    })


@app.route("/api/history/<file_id>", methods=["GET"])
@login_required
def history(file_id):
    user   = current_user()
    record = bc.get_file(file_id)
    if not record:
        return jsonify({"error": "File not found"}), 404
    if user["role"] != "admin":
        if user["username"] not in record.get("access_list", []):
            return jsonify({"error": "Access denied"}), 403
    return jsonify(bc.get_history(file_id))


@app.route("/api/files", methods=["GET"])
@login_required
def all_files():
    user = current_user()
    if user["role"] == "admin":
        return jsonify(bc.get_all_files())
    return jsonify(bc.get_files_for_user(user["username"]))


@app.route("/api/chain", methods=["GET"])
@login_required
def chain_info():
    """
    Called by the frontend every 5 seconds to poll chain status.
    Also used by the browser-side chain validator to fetch blocks.
    """
    return jsonify({
        "length":   len(bc.chain),
        "is_valid": bc.is_valid(),
        "blocks":   bc.to_list(),
    })


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
