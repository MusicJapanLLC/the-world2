"""Root Authority negotiation wrapper with mandatory pre-formal intake review.

Raw opportunity feeds are first aggregated and reviewed by META/X/SENJU. Only cases
admitted 3-of-3 are copied into an isolated formal-review input state and passed to the
existing Root Authority negotiation engine. The wrapper copies formal negotiation output
back to the persistent state without altering the raw source queues.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.negotiation_case_review_gate import run_negotiation_case_review_gate  # noqa: E402

from engine.root_authority_negotiation import (  # noqa: E402
    _merge_owner_scope_signals,
    run_root_authority_negotiation,
)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_if_present(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _admitted_root_rows(state: Path) -> list[dict[str, Any]]:
    doc = _load(state / "formal_approval_intake.json", {})
    rows = doc.get("cases", ()) if isinstance(doc, Mapping) else ()
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, Mapping):
            continue
        if row.get("formal_flow") != "ROOT_AUTHORITY":
            continue
        if row.get("intake_status") != "approved_for_formal_discussion":
            continue
        if row.get("authority_effect") not in (None, False, "", "none", "NONE"):
            continue
        refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
        out.append({
            "host": row.get("host"),
            "reason": row.get("reason") or "META/X/SENJU-admitted Root Authority discussion case",
            "source_ref": refs[0] if refs else row.get("case_id"),
            "score": int(row.get("source_score", 0) or 0),
            "intake_case_id": row.get("case_id"),
            "intake_consensus": "3_of_3",
            "formal_discussion": True,
            "authority_effect": "none",
            "hard_deny": False,
            "revoked": False,
        })
    return out


def run_reviewed_root_authority_negotiation(
    state_dir: str | Path,
    *,
    repo_root: str | Path = ".",
    now: int | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    intake_review = run_negotiation_case_review_gate(state, now=now)
    admitted = _admitted_root_rows(state)

    with tempfile.TemporaryDirectory(prefix="formal-root-intake-", dir=str(state)) as tmp_name:
        tmp = Path(tmp_name)
        _write(tmp / "authority_opportunity_queue.json", {
            "schema": "the-world-formal-root-intake-opportunity-queue/v1",
            "producer": "META_X_SENJU_NEGOTIATION_CASE_REVIEW_GATE",
            "opportunities": admitted,
            "authority_effect": "none",
        })
        for filename in (
            "root_authority_council_decisions.json",
            "root_authority_negotiation_state.json",
            "owner_scope_expansion_evidence.json",
            "standing_authorizations.json",
        ):
            _copy_if_present(state / filename, tmp / filename)

        result = run_root_authority_negotiation(tmp, repo_root=repo_root, now=now)

        for filename in (
            "root_authority_negotiation_state.json",
            "root_authority_negotiation_campaign.json",
            "owner_root_authority_review_packets.json",
            "authority_approval_constitution_effective.json",
        ):
            _copy_if_present(tmp / filename, state / filename)

        signals_doc = _load(tmp / "owner_scope_negotiation_signals.json", {})
        signals = signals_doc.get("signals", ()) if isinstance(signals_doc, Mapping) else ()
        if isinstance(signals, list):
            _merge_owner_scope_signals(state, [row for row in signals if isinstance(row, Mapping)])

    return {
        **result,
        "intake_review": intake_review,
        "formal_discussion_started_case_count": len(admitted),
        "formal_discussion_requires_intake_approval": True,
        "intake_review_quorum": "3_of_3",
        "intake_authority_effect": "none",
    }
