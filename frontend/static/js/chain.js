/**
 * chain.js — Browser-side blockchain engine
 *
 * Mirrors the Python blockchain logic using the Web Crypto API.
 * Runs entirely in the browser — no server involved.
 *
 * Exported as a global object: BrowserChain
 */

const BrowserChain = (() => {
  const DIFFICULTY    = 3;
  let   localChain    = [];
  let   validatedCount = 0;

  /* ── SHA-256 using native browser crypto ─────────────────────── */
  async function sha256(obj) {
    // Must serialise with sorted keys to match Python's json.dumps(sort_keys=True)
    const str  = JSON.stringify(obj, Object.keys(obj).sort());
    const buf  = new TextEncoder().encode(str);
    const hash = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(hash))
      .map(b => b.toString(16).padStart(2, "0"))
      .join("");
  }

  /* ── Validate a single block ─────────────────────────────────── */
  async function validateBlock(block) {
    // 1. Recompute the hash from the block's own fields
    const computed = await sha256({
      index:         block.index,
      timestamp:     block.timestamp,
      data:          block.data,
      previous_hash: block.previous_hash,
      nonce:         block.nonce,
    });

    // 2. Hash must match what is stored
    if (computed !== block.hash) return false;

    // 3. Hash must satisfy proof-of-work
    if (!block.hash.startsWith("0".repeat(DIFFICULTY))) return false;

    return true;
  }

  /* ── Validate the entire chain ───────────────────────────────── */
  async function validateChain(chain) {
    for (let i = 1; i < chain.length; i++) {
      if (!(await validateBlock(chain[i])))             return false;
      if (chain[i].previous_hash !== chain[i - 1].hash) return false;
    }
    return true;
  }

  /* ── Sync: accept a chain if it is longer and valid ─────────── */
  async function syncChain(chain) {
    if (chain.length <= localChain.length) return false;
    const valid = await validateChain(chain);
    if (!valid) return false;
    localChain = [...chain];
    return true;
  }

  /* ── Receive a single new block from WebSocket broadcast ─────── */
  async function receiveBlock(block) {
    const valid = await validateBlock(block);
    if (valid) {
      localChain.push(block);
      validatedCount++;
    }
    return valid;
  }

  /* ── Public interface ────────────────────────────────────────── */
  return {
    syncChain,
    receiveBlock,
    validateChain,
    validateBlock,
    getChain:     () => localChain,
    getValidated: () => validatedCount,
  };
})();
