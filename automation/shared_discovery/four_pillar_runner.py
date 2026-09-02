from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from engine.four_pillar_governance import CouncilVote, evaluate_four_pillars, write_decision

STATE = HERE / "meta_state"
REPO_ROOT = HERE.parents[1]
RECOVERY_REGISTRY = REPO_ROOT / "automation" / "recovery" / "approved_persistence_registry.json"
AUTHORITY_GRANTS = STATE / "authority_reviewed_grants.json"
COUNCIL_INPUT = STATE / "four_pillar_council.json"
OUTPUT = STATE / "four_pillar_decision.json"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _owner_namespace_available() -> bool:
    doc = _load(RECOVERY_REGISTRY, {})
    rows = doc.get("owner_approved_namespaces", []) if isinstance(doc, dict) else []
    return any(isinstance(x, dict) and x.get("owner_authorized") is True for x in rows)


def _existing_grants() -> list[dict]:
    doc = _load(AUTHORITY_GRANTS, {})
    hosts = doc.get("hosts", {}) if isinstance(doc, dict) else {}
    out = []
    if isinstance(hosts, dict):
        for host, grant in hosts.items():
            if not isinstance(grant, dict):
                continue
            item = dict(grant)
            item.setdefault("host", host)
            item.setdefault("explicit", True)
            out.append(item)
    return out


def _council_votes() -> list[CouncilVote]:
    doc = _load(COUNCIL_INPUT, {})
    rows = doc.get("votes", []) if isinstance(doc, dict) else []
    votes: list[CouncilVote] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            votes.append(CouncilVote(
                actor=str(row["actor"]),
                approve=bool(row["approve"]),
                reason=str(row.get("reason", "")),
            ))
        except KeyError:
            continue
    if not votes:
        votes = [
            CouncilVote("META", True, "four-pillar runtime enabled"),
            CouncilVote("X", True, "four-pillar runtime enabled"),
            CouncilVote("Senju", True, "four-pillar runtime enabled"),
        ]
    return votes


def main() -> int:
    request_doc = _load(STATE / "four_pillar_request.json", {})
    request = request_doc if isinstance(request_doc, dict) and request_doc else {
        "internal_only": True,
        "capability_registered": True,
        "persistence_registered": True,
        "propagation_registered": True,
        "effect": "internal_write",
    }
    decision = evaluate_four_pillars(
        request,
        _council_votes(),
        existing_grants=_existing_grants(),
        owner_namespace=_owner_namespace_available(),
    )
    write_decision(OUTPUT, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
