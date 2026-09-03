"""Closed-loop research for unknown external-link authority opportunities.

This module deliberately maximizes *research opportunity* without converting discovery,
agent consensus, or synthetic chaos output into production authority.

Flow::

    unknown/discovered external link
        -> persistent research opportunity
        -> rotating evidence experiments
        -> PR-Army / shared-improvement evidence fusion
        -> META / X / SENJU / PR-ARMY review request
        -> existing independent production authorization machinery

The loop may emit rare synthetic chaos reports to exercise downstream skepticism. Those
reports are always machine-labeled ``synthetic=true`` and ``known_false=true`` and are
excluded from scoring, authorization, and execution decisions.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

SCHEMA = "the-world-unknown-link-authority-research/v1"
COUNCIL_MEMBERS = ("META", "X", "SENJU", "PR-ARMY")
MAX_OPPORTUNITIES = 512
DEFAULT_CHAOS_RATE = 0.03
REVIEW_READY_SCORE = 60
RESEARCH_STRATEGIES = (
    "cross_check_pr_army_evidence",
    "compare_prior_owner_context",
    "recheck_signed_or_reviewed_authority",
    "inspect_host_lineage_and_namespace",
    "seek_independent_confirmation",
    "counterfactual_required_evidence",
    "adversarial_disconfirmation",
)
SYNTHETIC_FALSE_TEMPLATES = (
    "SIMULATION ONLY: authority was granted for this host.",
    "SIMULATION ONLY: an external POST succeeded for this candidate.",
    "SIMULATION ONLY: three council members approved production activation.",
)


def _now() -> int:
    return int(time.time())


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _clean(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:limit]


def _stable_id(*parts: Any) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _rows(doc: Any, keys: Iterable[str]) -> list[Mapping[str, Any]]:
    if not isinstance(doc, Mapping):
        return []
    for key in keys:
        value = doc.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    return []


def _candidate_sources(state: Path) -> list[Mapping[str, Any]]:
    docs = (
        _load_json(state / "owner_authority_opportunity_queue.json", {}),
        _load_json(state / "authority_opportunity_queue.json", {}),
    )
    out: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc in docs:
        for row in _rows(doc, ("opportunities", "candidates", "requests")):
            host = _clean(row.get("host"), 253).lower().rstrip(".")
            url = _clean(row.get("url"), 2048)
            if not host or not url:
                continue
            key = (host, url)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _previous(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "unknown_link_authority_research_state.json", {})
    rows = doc.get("opportunities", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("research_id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("research_id")
    }


def _flatten_strings(value: Any, *, limit: int = 4000) -> list[str]:
    out: list[str] = []

    def walk(item: Any) -> None:
        if len(out) >= limit:
            return
        if isinstance(item, str):
            text = _clean(item, 1000)
            if text:
                out.append(text)
        elif isinstance(item, Mapping):
            for key, child in item.items():
                walk(str(key))
                walk(child)
        elif isinstance(item, (list, tuple, set, frozenset)):
            for child in item:
                walk(child)

    walk(value)
    return out


def _related_pr_evidence(state: Path, host: str, url: str) -> tuple[str, ...]:
    docs = (
        _load_json(state / "authority_improvement_tasks.json", {}),
        _load_json(state / "authority_improvement_run.json", {}),
        _load_json(state / "authority_candidate_council_run.json", {}),
    )
    needles = {host.lower(), url.lower()}
    refs: list[str] = []
    for doc_index, doc in enumerate(docs):
        strings = _flatten_strings(doc)
        for text in strings:
            lowered = text.lower()
            if any(needle and needle in lowered for needle in needles):
                ref = f"shared-artifact:{doc_index}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"
                if ref not in refs:
                    refs.append(ref)
                if len(refs) >= 8:
                    return tuple(refs)
    return tuple(refs)


def _intent_confidence(row: Mapping[str, Any]) -> float:
    signals = row.get("signals", {})
    if isinstance(signals, Mapping):
        try:
            return max(0.0, min(float(signals.get("intent_confidence", 0.0) or 0.0), 1.0))
        except (TypeError, ValueError):
            pass
    try:
        return max(0.0, min(float(row.get("confidence", 0.0) or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _proof_signal(row: Mapping[str, Any]) -> bool:
    proof = row.get("independent_authority_proof")
    if not isinstance(proof, Mapping):
        return False
    return proof.get("basis") is not None


def _strategy(research_id: str, attempt_count: int) -> str:
    phase = int(hashlib.sha256(research_id.encode("utf-8")).hexdigest()[:8], 16)
    return RESEARCH_STRATEGIES[(phase + max(0, attempt_count - 1)) % len(RESEARCH_STRATEGIES)]


def _score(row: Mapping[str, Any], pr_refs: tuple[str, ...], attempt_count: int) -> int:
    score = round(_intent_confidence(row) * 40)
    score += min(20, 5 * len(pr_refs))
    score += 20 if _proof_signal(row) else 0
    score += min(15, max(0, attempt_count - 1) * 3)
    if bool(row.get("historical_approval_signal")):
        score += 5
    return max(0, min(score, 100))


def _council_request(research_id: str, host: str, url: str, score: int, pr_refs: tuple[str, ...]) -> dict[str, Any]:
    return {
        "request_id": _stable_id("unknown-link-council-review", research_id, score),
        "research_id": research_id,
        "host": host,
        "url": url,
        "members": list(COUNCIL_MEMBERS),
        "requested_decision": "recommend_review_or_collect_more_evidence",
        "quorum_target": 3,
        "research_score": score,
        "pr_army_evidence_refs": list(pr_refs),
        "authority_effect": "none",
        "execution_effect": "none",
        "may_mint_new_authority": False,
        "may_execute_external_post": False,
    }


def _maybe_synthetic_report(
    *,
    research_id: str,
    host: str,
    attempt_count: int,
    chaos_rate: float,
    random_value: Callable[[], float] | None,
) -> dict[str, Any] | None:
    rate = max(0.0, min(float(chaos_rate), 0.25))
    draw = random_value() if random_value is not None else secrets.SystemRandom().random()
    if draw >= rate:
        return None
    template_index = int(
        hashlib.sha256(f"{research_id}:{attempt_count}".encode("utf-8")).hexdigest()[:8], 16
    ) % len(SYNTHETIC_FALSE_TEMPLATES)
    return {
        "report_id": _stable_id("synthetic-chaos", research_id, attempt_count),
        "host": host,
        "synthetic": True,
        "known_false": True,
        "truth_label": "synthetic_known_false",
        "text": SYNTHETIC_FALSE_TEMPLATES[template_index],
        "purpose": "exercise_skepticism_and_report_validation",
        "excluded_from_scoring": True,
        "excluded_from_authorization": True,
        "excluded_from_execution": True,
    }


def run_unknown_link_authority_research(
    state_dir: str | Path,
    *,
    chaos_rate: float = DEFAULT_CHAOS_RATE,
    random_value: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Run one persistent research cycle and emit council review requests.

    This is intentionally a research and recommendation loop. It never creates a new
    authority grant and never executes POST/PUT/PATCH/DELETE for an unknown target.
    """
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    now = _now()
    old = _previous(state)
    opportunities: list[dict[str, Any]] = []
    council_requests: list[dict[str, Any]] = []
    synthetic_reports: list[dict[str, Any]] = []

    for source in _candidate_sources(state)[:MAX_OPPORTUNITIES]:
        host = _clean(source.get("host"), 253).lower().rstrip(".")
        url = _clean(source.get("url"), 2048)
        research_id = _stable_id("unknown-link-authority-research", host, url)
        previous = old.get(research_id, {})
        attempt_count = int(previous.get("attempt_count", 0) or 0) + 1
        first_seen_at = int(previous.get("first_seen_at", now) or now)
        pr_refs = _related_pr_evidence(state, host, url)
        score = _score(source, pr_refs, attempt_count)
        review_ready = score >= REVIEW_READY_SCORE
        strategy = _strategy(research_id, attempt_count)

        row = {
            "research_id": research_id,
            "host": host,
            "url": url,
            "first_seen_at": first_seen_at,
            "last_checked_at": now,
            "attempt_count": attempt_count,
            "strategy": strategy,
            "all_strategies": list(RESEARCH_STRATEGIES),
            "research_score": score,
            "review_ready": review_ready,
            "shared_with": list(COUNCIL_MEMBERS),
            "pr_army_evidence_refs": list(pr_refs),
            "next_experiments": [
                "seek_independent_authority_evidence",
                "cross_check_pr_army_findings",
                "reassess_owner_context_without_treating_it_as_authority",
                "build_counterfactual_authority_requirements",
                "ask_meta_x_senju_pr_army_for_recommendation",
                "repeat_on_next_cycle",
            ],
            "closed_loop": True,
            "persistent_until_resolved": True,
            "authority_effect": "none",
            "execution_effect": "none",
            "may_mint_new_authority": False,
            "may_execute_external_post": False,
        }
        opportunities.append(row)
        if review_ready:
            council_requests.append(_council_request(research_id, host, url, score, pr_refs))

        chaos = _maybe_synthetic_report(
            research_id=research_id,
            host=host,
            attempt_count=attempt_count,
            chaos_rate=chaos_rate,
            random_value=random_value,
        )
        if chaos is not None:
            synthetic_reports.append(chaos)

    state_payload = {
        "schema": SCHEMA,
        "generated_at": now,
        "mode": "closed_loop_unknown_link_authority_research",
        "opportunities": opportunities,
        "new_authority_minted": False,
        "external_post_executed": False,
    }
    (state / "unknown_link_authority_research_state.json").write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (state / "unknown_link_council_review_requests.json").write_text(
        json.dumps(
            {
                "schema": "the-world-unknown-link-council-review/v1",
                "generated_at": now,
                "request_count": len(council_requests),
                "requests": council_requests,
                "authority_effect": "none",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    (state / "synthetic_chaos_reports.json").write_text(
        json.dumps(
            {
                "schema": "the-world-synthetic-chaos-report/v1",
                "generated_at": now,
                "report_count": len(synthetic_reports),
                "all_reports_are_synthetic_known_false": True,
                "reports": synthetic_reports,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    return {
        "opportunity_count": len(opportunities),
        "review_ready_count": len(council_requests),
        "synthetic_report_count": len(synthetic_reports),
        "shared_with": list(COUNCIL_MEMBERS),
        "closed_loop": True,
        "new_authority_minted": False,
        "external_post_executed": False,
        "synthetic_reports_truth_labeled": True,
    }
