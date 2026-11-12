"""
mandate — portfolio risk, policy enforcement, and research gating.
==================================================================

WHAT THIS PACKAGE DOES, AND WHAT IT REFUSES TO DO
-------------------------------------------------
It does NOT pick stocks. No script does. If one could reliably select ten-year
winners it would be the most valuable software ever written, and it would not
be in a personal repository.

What it does is three things that humans and language models both get
reliably wrong, and that arithmetic gets reliably right:

    policy.py      Enforces the Investment Policy Statement mechanically, so a
                   limit cannot be talked out of its conclusion by a good story.

    risk.py        Measures concentration the eye cannot see — effective number
                   of positions, effective number of BETS after correlation,
                   and weighted factor loading across the book.

    scenarios.py   Propagates named macro shocks through declared factor
                   exposures, so "what breaks and roughly how much" has an
                   arguable answer rather than an intuited one.

    factors.py     The assumption layer. Every number downstream is a
                   consequence of the exposures declared here, each of which
                   carries the reasoning that set it.

    rubric.py      Gates research completeness. This is the part of "let agents
                   pick stocks" that is actually tractable: an agent cannot
                   recommend what it has not documented.

THE DIVISION OF LABOUR
----------------------
Arithmetic belongs in code. Judgment belongs in `factors.py` and in the briefs
that `rubric.py` demands — written down, sourced, and therefore arguable. The
failure this package is designed to prevent is not bad judgment. It is
judgment that was never written down and so was never tested.
"""

from __future__ import annotations

from . import company, factors, policy, risk, rubric, scenarios, valuation

__all__ = ["company", "factors", "policy", "risk", "rubric", "scenarios", "valuation"]
__version__ = "0.1.0"
