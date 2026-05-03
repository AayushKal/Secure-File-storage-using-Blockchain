import hashlib
import json
import os
import time

from pymongo import MongoClient, ASCENDING

DIFFICULTY = 3
MONGO_URI  = os.getenv("MONGO_URI", "")
DB_NAME    = "chainvault"

# ── MongoDB connection ────────────────────────────────────────────────────────
_mongo_col = None

def _get_col():
    """Return the blocks collection, or None if MONGO_URI is not configured."""
    global _mongo_col
    if not MONGO_URI:
        return None
    if _mongo_col is None:
        client     = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db         = client[DB_NAME]
        _mongo_col = db["blocks"]
        _mongo_col.create_index([("index", ASCENDING)], unique=True)
    return _mongo_col


# ── Block ─────────────────────────────────────────────────────────────────────
class Block:
    def __init__(self, index, data, previous_hash,
                 nonce=0, timestamp=None, hash=None):
        self.index         = index
        self.timestamp     = timestamp or time.time()
        self.data          = data
        self.previous_hash = previous_hash
        self.nonce         = nonce
        self.hash          = hash or self.compute_hash()

    def compute_hash(self):
        content = json.dumps({
            "index":         self.index,
            "timestamp":     self.timestamp,
            "data":          self.data,
            "previous_hash": self.previous_hash,
            "nonce":         self.nonce,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def mine(self):
        target = "0" * DIFFICULTY
        while not self.hash.startswith(target):
            self.nonce += 1
            self.hash = self.compute_hash()

    def to_dict(self):
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "data":          self.data,
            "previous_hash": self.previous_hash,
            "nonce":         self.nonce,
            "hash":          self.hash,
        }


# ── Blockchain ────────────────────────────────────────────────────────────────
class Blockchain:
    def __init__(self):
        self.chain = []
        self._load()
        if not self.chain:
            self._create_genesis()

    # ── Genesis ───────────────────────────────────────────────────────────────
    def _create_genesis(self):
        g = Block(0, {"type": "GENESIS", "message": "Genesis Block"}, "0")
        g.mine()
        self.chain.append(g)
        self._save_block(g)

    # ── Add record ────────────────────────────────────────────────────────────
    def add_record(self, data: dict) -> Block:
        block = Block(len(self.chain), data, self.chain[-1].hash)
        block.mine()
        self.chain.append(block)
        self._save_block(block)
        return block

    # ── Validation ────────────────────────────────────────────────────────────
    def is_valid(self) -> bool:
        for i in range(1, len(self.chain)):
            cur  = self.chain[i]
            prev = self.chain[i - 1]
            if cur.hash != cur.compute_hash():
                return False
            if cur.previous_hash != prev.hash:
                return False
        return True

    # ── Query helpers ─────────────────────────────────────────────────────────
    def get_file(self, file_id: str) -> dict | None:
        result = None
        for block in self.chain:
            if isinstance(block.data, dict) and block.data.get("file_id") == file_id:
                result = block.data
        return result

    def get_history(self, file_id: str) -> list:
        return [
            b.to_dict() for b in self.chain
            if isinstance(b.data, dict) and b.data.get("file_id") == file_id
        ]

    def get_all_files(self) -> list:
        seen = {}
        for block in self.chain:
            d = block.data
            if isinstance(d, dict) and "file_id" in d:
                seen[d["file_id"]] = d
        return list(seen.values())

    def get_files_for_user(self, username: str) -> list:
        return [
            f for f in self.get_all_files()
            if f.get("owner") == username
            or username in f.get("access_list", [])
        ]

    def to_list(self) -> list:
        return [b.to_dict() for b in self.chain]

    # ── Persistence (MongoDB) ─────────────────────────────────────────────────
    def _save_block(self, block: Block):
        """Upsert one block document by index. No-op if MongoDB not configured."""
        col = _get_col()
        if col is None:
            return
        doc = block.to_dict()
        col.update_one({"index": block.index}, {"$set": doc}, upsert=True)

    def _load(self):
        """Load entire chain from MongoDB on startup."""
        col = _get_col()
        if col is None:
            return          # no DB — start fresh in memory
        try:
            docs = list(col.find({}, {"_id": 0}).sort("index", ASCENDING))
            self.chain = [Block(**d) for d in docs]
        except Exception as e:
            print(f"[Chain] MongoDB load failed: {e} — starting fresh")
            self.chain = []
