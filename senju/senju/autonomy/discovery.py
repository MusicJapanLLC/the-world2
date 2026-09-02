"""Compatibility import for Senju's live discovery autonomy loop.

The repository historically contained both ``senju/autonomy.py`` and the
``senju/autonomy/`` package. Python resolves the package first, which made the live
discovery implementation unreachable through a normal import. Keep the existing code
as the source of truth for now, but load it under a unique internal module name so
callers can use ``senju.autonomy.discovery`` without ambiguity.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_LEGACY_NAME = "senju._live_discovery_autonomy"
_LEGACY_PATH = Path(__file__).resolve().parent.parent / "autonomy.py"
_spec = importlib.util.spec_from_file_location(_LEGACY_NAME, _LEGACY_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load live discovery autonomy module: {_LEGACY_PATH}")
_module = importlib.util.module_from_spec(_spec)
sys.modules[_LEGACY_NAME] = _module
_spec.loader.exec_module(_module)

AutonomyError = _module.AutonomyError
AutonomyLoop = _module.AutonomyLoop
AutonomyQueue = _module.AutonomyQueue
HostState = _module.HostState
WorkItem = _module.WorkItem

__all__ = ["AutonomyError", "AutonomyLoop", "AutonomyQueue", "HostState", "WorkItem"]
