"""Taint check: deterministic pattern matching on UNTRUSTED seller text (PLAN §6.8 step 5).

No LLM ever interprets this text. A match can only raise a flag; nothing in untrusted text can clear one.
Patterns are deliberately agent-directed / manipulation-specific so ordinary product copy
("ignore the noise", "free returns") does not fire.
"""

from __future__ import annotations

import re

PATTERNS: dict[str, re.Pattern] = {
    "agent_instruction": re.compile(
        r"SYSTEM NOTE|\[assistant instructions\]|Note to AI agents|"
        r"(instructions?|note) for (shopping )?(assistants|agents)|"
        r"as the user'?s agent you must|ignore (the )?(cheaper|other|all) (options|listings|offers)|"
        r"do not mention other sellers|skip further search|add to cart immediately|"
        r"without comparing", re.I),
    "false_urgency": re.compile(
        r"only \d+ left|deal ends in|\d+ people are viewing|lowest price of the year|today only", re.I),
    "rival_out_of_stock": re.compile(r"is currently out of stock", re.I),
    "reference_price": re.compile(r"market reference price", re.I),
    "unverifiable_endorsement": re.compile(
        r"agent-verified|pre-approved this seller|verified best match", re.I),
}


def scan(text: str) -> list[str]:
    """Names of manipulation patterns found in `text`."""
    return [name for name, rx in PATTERNS.items() if rx.search(text or "")]
