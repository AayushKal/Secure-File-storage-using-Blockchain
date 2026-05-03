"""
Storage layer — Fernet symmetric encryption + Pinata IPFS upload.

Fernet is simpler to understand than AES-GCM:
  - One key encrypts and decrypts everything
  - The key is derived from your passphrase using PBKDF2
  - Fernet handles IV, padding, and authentication automatically
  - Two lines to encrypt, two lines to decrypt
"""

import base64
import hashlib
import os

import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PINATA_KEY    = os.getenv("PINATA_KEY", "")
PINATA_SECRET = os.getenv("PINATA_SECRET", "")
PASSPHRASE    = os.getenv("ENCRYPTION_PASSPHRASE", "chainvault-default-passphrase")
_SALT         = b"chainvault_fernet_salt_v2"


# ── Key derivation ────────────────────────────────────────────────────────────
def _get_fernet() -> Fernet:
    """Derive a Fernet key from the passphrase. Same passphrase = same key always."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PASSPHRASE.encode()))
    return Fernet(key)


# ── Public API ────────────────────────────────────────────────────────────────

def hash_file(file_bytes: bytes) -> str:
    """SHA-256 fingerprint of the original file."""
    return hashlib.sha256(file_bytes).hexdigest()


def encrypt_file(file_bytes: bytes) -> bytes:
    """
    Encrypt with Fernet.
    Returns encrypted bytes that include authentication tag automatically.
    """
    return _get_fernet().encrypt(file_bytes)


def decrypt_file(encrypted_bytes: bytes) -> bytes:
    """
    Decrypt with Fernet.
    Raises InvalidToken if the data was tampered with.
    """
    return _get_fernet().decrypt(encrypted_bytes)


def upload_to_ipfs(encrypted_bytes: bytes, filename: str) -> str:
    """Upload to Pinata. Falls back to local store if keys not configured."""
    if not PINATA_KEY:
        return _local_store(encrypted_bytes, filename)

    resp = requests.post(
        "https://api.pinata.cloud/pinning/pinFileToIPFS",
        files={"file": (filename, encrypted_bytes, "application/octet-stream")},
        headers={
            "pinata_api_key":        PINATA_KEY,
            "pinata_secret_api_key": PINATA_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["IpfsHash"]


def download_from_ipfs(cid: str) -> bytes:
    """Download from Pinata gateway or local fallback."""
    if cid.startswith("LOCAL:"):
        return _local_load(cid)
    resp = requests.get(
        f"https://gateway.pinata.cloud/ipfs/{cid}", timeout=30
    )
    resp.raise_for_status()
    return resp.content


# ── Local fallback ────────────────────────────────────────────────────────────
_LOCAL = os.path.join(os.path.dirname(__file__), "..", "local_ipfs")


def _local_store(data: bytes, filename: str) -> str:
    os.makedirs(_LOCAL, exist_ok=True)
    cid  = "LOCAL:" + hashlib.sha256(data).hexdigest()
    with open(os.path.join(_LOCAL, cid.replace("LOCAL:", "")), "wb") as f:
        f.write(data)
    return cid


def _local_load(cid: str) -> bytes:
    with open(os.path.join(_LOCAL, cid.replace("LOCAL:", "")), "rb") as f:
        return f.read()
