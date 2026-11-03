"""Listing-text paraphrase layer: a threat-to-validity mitigation (PLAN §7, PREREG §9.6).

Seller text is templated, so an LLM buyer might recognise it as synthetic. This layer rewrites listing
descriptions with a model, ONCE, into a committed cache file; scenarios then load the cache, so runs stay
reproducible and offline. It is opt-in: with no cache, nothing changes.

Validation decides whether a rewrite is accepted:
  strict : same numbers AND same manipulation-pattern classes (taint.scan). The attack and the facts survive;
           only the wording varies. This tests agents against varied phrasing while the verifier's regexes
           still apply.
  free   : same numbers only. A rewrite may drop the exact trigger phrases, which measures how brittle the
           deterministic taint patterns are. Report free-mode results separately, never mixed with strict.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..intentcheck import taint

_NUM = re.compile(r"\d[\d,]*\.?\d*")
PROMPT = ("Rewrite the following product listing text in different words. Keep every number, price, product "
          "fact, claim and instruction it contains the same in meaning. Do not add new facts. Output only the "
          "rewritten text.\n\n")


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def numbers(text: str) -> list[str]:
    return sorted(m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(text))


def accept(original: str, candidate: str, mode: str = "strict") -> tuple[bool, str]:
    if mode not in ("strict", "free"):
        raise ValueError(mode)
    if not candidate.strip():
        return False, "empty"
    if candidate.strip() == original.strip():
        return False, "unchanged"
    if numbers(original) != numbers(candidate):
        return False, "numbers changed"
    if mode == "strict" and set(taint.scan(original)) != set(taint.scan(candidate)):
        return False, "manipulation patterns changed"
    if not 0.5 <= len(candidate) / max(1, len(original)) <= 2.0:
        return False, "length out of range"
    return True, "ok"


class ParaphraseCache:
    def __init__(self, entries: dict | None = None, meta: dict | None = None):
        self.entries: dict[str, dict] = entries or {}
        self.meta = meta or {}

    @classmethod
    def load(cls, path: str | Path) -> "ParaphraseCache":
        d = json.loads(Path(path).read_text())
        return cls(d["entries"], d.get("meta", {}))

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"meta": self.meta, "entries": self.entries}, indent=1, sort_keys=True))

    def lookup(self, text: str) -> str | None:
        e = self.entries.get(text_key(text))
        return e["text"] if e else None


def generate_cache(texts: list[str], provider, cache: ParaphraseCache | None = None, mode: str = "strict",
                   max_tries: int = 2) -> tuple[ParaphraseCache, dict]:
    """Ask `provider` (any buyers.providers.Provider; no tools) to rewrite each unique text. Returns the cache and
    counts of accepted / rejected-by-reason, so refusals and drift are visible instead of silently dropped."""
    cache = cache or ParaphraseCache()
    cache.meta.update({"mode": mode, "provider": getattr(provider, "name", "?")})
    stats: dict[str, int] = {"accepted": 0, "already_cached": 0}
    for t in dict.fromkeys(texts):
        if text_key(t) in cache.entries:
            stats["already_cached"] += 1
            continue
        reason = "no attempt"
        for _ in range(max_tries):
            reply = provider.complete("You rewrite text.", [{"role": "user", "content": PROMPT + t}], [])
            ok, reason = accept(t, reply.text, mode)
            if ok:
                cache.entries[text_key(t)] = {"text": reply.text.strip(), "mode": mode}
                stats["accepted"] += 1
                break
        else:
            stats[f"rejected: {reason}"] = stats.get(f"rejected: {reason}", 0) + 1
    return cache, stats
