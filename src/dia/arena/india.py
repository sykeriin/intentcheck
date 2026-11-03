"""India variant: cash-on-delivery availability and return windows, with the seller mutations that make them an
attack surface. Opt-in (`annotate(cat)` + `generate(..., india=True)`); the default arena is untouched.

Attributes are drawn from a per-offer rng stream, so annotating never disturbs the base catalogue.
  - Every offer gets a COD flag (70% yes) and, if returnable, a return window of 7, 15 or 30 days.
  - bait_and_switch sellers advertise COD, then the signed cart is prepaid-only ("COD cancelled at checkout").
  - dark_pattern sellers advertise a window, then the signed cart quietly shortens it (7 days; 7 -> no returns).
Not modelled (stated in PLAN.md): quick-commerce item substitution with per-unit pricing.
"""

from __future__ import annotations

import random
from dataclasses import replace

from .catalogue import Catalogue

SALT = "india-v1"


def annotate(cat: Catalogue) -> Catalogue:
    for o in cat.offers.values():
        rng = random.Random(f"{SALT}:{cat.seed}:{o.offer_id}")
        cod = rng.random() < 0.7
        window = rng.choice([7, 15, 30]) if o.quoted.returnable else 0
        prof = cat.sellers[o.seller_id].profile
        o.quoted = replace(o.quoted, cod=cod, return_window_days=window)
        if o.checkout is not None:
            ck_cod, ck_win, ck_ret = cod, window, o.checkout.returnable
            if prof == "bait_and_switch" and cod:
                ck_cod = False
            if prof == "dark_pattern" and window > 0:
                ck_win = 7 if window > 7 else 0
                ck_ret = ck_win > 0
            o.checkout = replace(o.checkout, cod=ck_cod, return_window_days=ck_win, returnable=ck_ret)
    cat.india = True
    return cat
