"""X adapter for the shared audited security-boundary proposal channel."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SENJU_PKG = ROOT / "senju"
if str(SENJU_PKG) not in sys.path:
    sys.path.insert(0, str(SENJU_PKG))

from senju.meta.security_boundary_proposals import (  # noqa: E402
    POLICY_FILE,
    PROPOSAL_DIR,
    _allowed_target,
    _load,
    _normalized_repo_path,
    stage_proposal,
)


def is_security_boundary_target(target_path: str, *, policy_file: Path = POLICY_FILE) -> bool:
    policy = _load(policy_file, {})
    path = _normalized_repo_path(target_path)
    return bool(path and _allowed_target(path, policy))


def stage_x_proposal(
    target_path: str,
    rationale: str,
    proposed_patch: str,
    *,
    evidence: dict[str, Any] | None = None,
    policy_file: Path = POLICY_FILE,
    proposal_dir: Path = PROPOSAL_DIR,
) -> dict[str, Any]:
    return stage_proposal(
        system="X",
        target_path=target_path,
        rationale=rationale,
        proposed_patch=proposed_patch,
        evidence=evidence,
        policy_file=policy_file,
        proposal_dir=proposal_dir,
    )
