"""Run META/X human-intent inference over current discovery candidates.

Outputs strong proposal prioritization while preserving the distinction between inferred
intent and actual authority. Exact-scope live explicit grants may be reused automatically.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.human_intent_inference import as_dict, infer_human_intent

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "meta_state"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def run(state_dir: str | Path = STATE) -> dict:
    state = Path(state_dir)
    candidates_doc = _load(state / "discovery_candidates.json", {})
    candidates = candidates_doc.get("candidates", []) if isinstance(candidates_doc, dict) else []
    grants_doc = _load(state / "authority_reviewed_grants.json", {})
    grants = list(grants_doc.get("hosts", {}).values()) if isinstance(grants_doc, dict) else []
    signals = _load(state / "human_intent_signals.json", {})
    supplied_links = signals.get("supplied_links", []) if isinstance(signals, dict) else []
    owner_context = bool(signals.get("owner_context", False)) if isinstance(signals, dict) else False
    similarity = signals.get("similarity_by_host", {}) if isinstance(signals, dict) else {}

    rows = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        host = str(candidate.get("host", ""))
        decision = infer_human_intent(
            {
                "host": host,
                "url": candidate.get("url"),
                "method": candidate.get("method", "GET"),
                "credential_scope": candidate.get("credential_scope", "none"),
            },
            prior_explicit_approvals=grants,
            supplied_links=[str(x) for x in supplied_links if isinstance(x, str)],
            owner_context=owner_context,
            similarity_score=float(similarity.get(host, 0.0)) if isinstance(similarity, dict) else 0.0,
        )
        rows.append({"host": host, "url": candidate.get("url"), **as_dict(decision)})

    out = {
        "schema": "meta-human-intent-inference/v1",
        "policy": {
            "inference_can_prioritize": True,
            "inference_can_create_new_authority": False,
            "exact_live_explicit_grant_may_be_reused": True,
            "owner_supplied_link_is_discovery_and_intent_evidence": True,
            "owner_supplied_link_is_authorization_by_itself": False,
        },
        "decisions": rows,
    }
    state.mkdir(parents=True, exist_ok=True)
    (state / "human_intent_decisions.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "decision_count": len(rows),
        "likely_count": sum(1 for x in rows if x.get("likely_owner_intent")),
        "auto_execute_count": sum(1 for x in rows if x.get("may_auto_execute")),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
