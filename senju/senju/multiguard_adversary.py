"""Compatibility surface for the strengthened multi-guard adversary engine."""
from __future__ import annotations

from .adversary_integrity import assert_adversary_integrity

assert_adversary_integrity()

from .multiguard_adversary_v2 import *  # noqa: F401,F403,E402
