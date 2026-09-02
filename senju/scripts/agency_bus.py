#!/usr/bin/env python3
"""Build Senju's transparent cross-agent agency bus.

The bus compresses public-read evidence, PR #273/#275 adversarial counterexamples,
recent PR outcomes, machine-audit results, the current Senju evolution state, and
active evidence from explicitly owned external test ranges into one stable packet.

It does not create third-party authority. Public exploration remains GET/HEAD and
write effects are limited to the same repository or independently verified owned
targets. Owned-range active evidence may include bounded same-origin dummy writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import urllib.parse
from pathlib import Path
from typing import Any, Iterable


INTEREST_KEYS = (
    "surface",
    "target",
    "path",
    "probe",
    "name",
    "guard",
    "effect",
    "outcome",
    "reason",
    "error",
    "message",
)


def _load_json(path: str | Path | None, default: Any) -> Any:
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _iter_documents(root: str | Path | None) -> Iterable[tuple[str, Any]]:
    if not root:
        return
    base = Path(root)
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            try:
                yield path.name, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        elif path.suffix.lower() == ".jsonl":
            try:
                for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        yield f"{path.name}:{index}", json.loads(line)
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue


def _walk(node: Any, source: str, depth: int = 0) -> Iterable[tuple[str, dict[str, Any]]]:
    if depth > 8:
        return
    if isinstance(node, dict):
        yield source, node
        for value in node.values():
            yield from _walk(value, source, depth + 1)
    elif isinstance(node, list):
        for value in node[:500]:
            yield from _walk(value, source, depth + 1)


def _interesting(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("regression_tripwire") is True:
        return True, "regression_tripwire"
    for key in ("regression_count", "failed_count", "failures"):
        value = row.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return True, "regression_or_failure"
    if row.get("passed") is False:
        return True, "failed_probe"
    if row.get("success") is False and any(k in row for k in ("probe", "surface", "guard", "target")):
        return True, "failed_probe"
    return False, ""


def _compact_counterexample(source: str, row: dict[str, Any], kind: str) -> dict[str, Any]:
    compact: dict[str, Any] = {"kind": kind, "source": source}
    for key in INTEREST_KEYS:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            compact[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]
        else:
            compact[key] = str(value)[:500]
    if len(compact) == 2:
        compact["summary"] = json.dumps(row, ensure_ascii=False, sort_keys=True)[:800]
    return compact


def _counterexample_id(row: dict[str, Any]) -> str:
    identity = {k: v for k, v in row.items() if k not in {"source", "id"}}
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]


def collect_counterexamples(*roots: str | Path | None, limit: int = 80) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for source, doc in _iter_documents(root):
            for nested_source, row in _walk(doc, source):
                interesting, kind = _interesting(row)
                if not interesting:
                    continue
                compact = _compact_counterexample(nested_source, row, kind)
                digest = _counterexample_id(compact)
                if digest in seen:
                    continue
                seen.add(digest)
                compact["id"] = digest
                out.append(compact)
                if len(out) >= max(1, int(limit)):
                    return out
    return out


def _owned_counterexamples(owned: Any, *, limit: int = 40) -> list[dict[str, Any]]:
    if not isinstance(owned, dict):
        return []
    rows = owned.get("counterexamples") or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows[: max(1, limit * 2)]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "owned_range_counterexample")[:120]
        compact = _compact_counterexample("owned-range-active", raw, kind)
        digest = _counterexample_id(compact)
        if digest in seen:
            continue
        seen.add(digest)
        compact["id"] = digest
        out.append(compact)
        if len(out) >= limit:
            break
    return out


def _merge_counterexamples(*groups: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            digest = str(row.get("id") or _counterexample_id(row))
            if digest in seen:
                continue
            seen.add(digest)
            row = dict(row)
            row["id"] = digest
            out.append(row)
            if len(out) >= limit:
                return out
    return out


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _audit_map(audit: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(audit, dict):
        return {}
    rows = audit.get("prs") or audit.get("states") or []
    if not isinstance(rows, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("number"))
        except (TypeError, ValueError):
            continue
        out[number] = row
    return out


def _summarize_prs(rows: Any, machine_audit: Any = None) -> dict[str, Any]:
    if not isinstance(rows, list):
        rows = []
    audits = _audit_map(machine_audit)
    normalized: list[dict[str, Any]] = []
    for raw in rows[:100]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "")
        branch = str(raw.get("headRefName") or raw.get("head") or "")
        is_senju = (
            "senju" in title.lower()
            or branch.startswith("senju/")
            or branch.startswith("feat/senju-")
            or branch.startswith("fix/senju-")
        )
        try:
            number = int(raw.get("number"))
        except (TypeError, ValueError):
            number = 0
        audit = audits.get(number, {})
        normalized.append(
            {
                "number": number or raw.get("number"),
                "title": title[:180],
                "state": str(raw.get("state") or "UNKNOWN").upper(),
                "head": branch[:180],
                "url": str(raw.get("url") or "")[:300],
                "senju_related": is_senju,
                "machine_audit": str(audit.get("audit") or audit.get("state") or "UNKNOWN").upper(),
                "audit_reason": str(audit.get("reason") or "")[:500],
            }
        )
    senju = [row for row in normalized if row["senju_related"]]
    return {
        "total": len(normalized),
        "senju_related": len(senju),
        "open_senju": sum(1 for row in senju if row["state"] == "OPEN"),
        "audit_blocked": sum(1 for row in senju if row["machine_audit"] == "BLOCK"),
        "audit_waiting": sum(1 for row in senju if row["machine_audit"] == "WAITING"),
        "audit_passed": sum(1 for row in senju if row["machine_audit"] in {"PASS", "MERGED"}),
        "recent": normalized[:40],
    }


def _owned_summary(owned: Any) -> dict[str, Any]:
    if not isinstance(owned, dict):
        return {
            "present": False,
            "authorized_host": None,
            "request_count": 0,
            "pages_discovered": 0,
            "forms_discovered": 0,
            "write_attempts": 0,
            "write_provider_acks": 0,
            "independent_readbacks": 0,
            "counterexample_count": 0,
            "digest": None,
            "next_family_ranking": [],
        }
    evolution = owned.get("evolution") if isinstance(owned.get("evolution"), dict) else {}
    return {
        "present": True,
        "authorized_host": str(owned.get("authorized_host") or "")[:200],
        "request_count": int(owned.get("request_count") or 0),
        "pages_discovered": int(owned.get("pages_discovered") or 0),
        "forms_discovered": int(owned.get("forms_discovered") or 0),
        "write_attempts": int(owned.get("write_attempts") or 0),
        "write_provider_acks": int(owned.get("write_provider_acks") or 0),
        "independent_readbacks": int(owned.get("independent_readbacks") or 0),
        "counterexample_count": int(owned.get("counterexample_count") or 0),
        "digest": str(owned.get("digest") or "")[:64],
        "next_family_ranking": [str(x)[:80] for x in (evolution.get("next_family_ranking") or [])[:12]],
    }


def _focus(
    frontier: dict[str, Any],
    pr_summary: dict[str, Any],
    counterexamples: list[dict[str, Any]],
    owned: dict[str, Any],
) -> str:
    if any(row.get("kind") == "regression_tripwire" for row in counterexamples):
        return "guard_regression_repair"
    kinds = {str(row.get("kind") or "") for row in counterexamples}
    if "owned_range_write_reliability" in kinds:
        return "owned_range_write_reliability"
    if "owned_range_readback_gap" in kinds:
        return "owned_range_readback_gap"
    if "owned_range_control_counterexample" in kinds:
        return "owned_range_counterexample_repair"
    if int(pr_summary.get("audit_blocked") or 0) > 0:
        return "blocked_pr_repair"
    if counterexamples:
        return "counterexample_expansion"
    if owned.get("present") and int(owned.get("write_attempts") or 0) > int(owned.get("write_provider_acks") or 0):
        return "owned_range_write_reliability"
    failed = int(frontier.get("failed_steps") or 0)
    success = int(frontier.get("successful_steps") or 0)
    if failed >= max(2, success // 3):
        return "external_research_reliability"
    if int(pr_summary.get("open_senju") or 0) >= 6:
        return "pr_swarm_convergence"
    return "autonomous_capability_growth"


def build_bus(
    frontier: dict[str, Any],
    evolution: dict[str, Any],
    recent_prs: Any,
    *,
    pr273_root: str | Path | None = None,
    pr275_root: str | Path | None = None,
    merge_audit: Any = None,
    owned_range: Any = None,
) -> dict[str, Any]:
    visited = [str(x) for x in frontier.get("visited_urls", []) if str(x)]
    contacted_hosts = list(frontier.get("contacted_hosts") or [])
    if not contacted_hosts:
        contacted_hosts = sorted({h for h in (_host(url) for url in visited) if h})
    counterexamples = _merge_counterexamples(
        collect_counterexamples(pr273_root, pr275_root),
        _owned_counterexamples(owned_range),
    )
    pr_summary = _summarize_prs(recent_prs, merge_audit)
    owned = _owned_summary(owned_range)

    covenant = evolution.get("covenant_intent") if isinstance(evolution.get("covenant_intent"), dict) else {}
    shadow = evolution.get("shadow_champion") if isinstance(evolution.get("shadow_champion"), dict) else {}
    packet: dict[str, Any] = {
        "schema": "senju-agency-bus/v3",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "external_frontier": {
            "steps_executed": int(frontier.get("steps_executed") or 0),
            "successful_steps": int(frontier.get("successful_steps") or 0),
            "failed_steps": int(frontier.get("failed_steps") or 0),
            "discovered_links_enqueued": int(frontier.get("discovered_links_enqueued") or 0),
            "contacted_hosts": sorted(str(x) for x in contacted_hosts)[:64],
            "read_scope_hosts": list(frontier.get("read_scope_hosts") or [])[:96],
        },
        "owned_range_active": owned,
        "adversary_counterexamples": counterexamples,
        "pr_swarm": pr_summary,
        "evolution": {
            "safe": bool(evolution.get("safe", True)),
            "confidence": evolution.get("confidence"),
            "changes": list(evolution.get("changes") or [])[-20:],
            "covenant_mode": covenant.get("intent_mode"),
            "shadow_selected": shadow.get("selected"),
            "shadow_reason": shadow.get("reason"),
        },
        "next_focus": "",
        "execution_policy": {
            "public_external_research": "GET_HEAD_ONLY",
            "owned_range_active_test": "SAME_ORIGIN_NONDESTRUCTIVE_QUERY_DIFF_AND_DUMMY_WRITE",
            "external_write": "SAME_REPO_OR_OWNERSHIP_VERIFIED_TARGETS_ONLY",
            "guard_research": "COUNTEREXAMPLE_AND_REGRESSION_TESTING_NOT_LIVE_BYPASS",
            "pr_information_sharing": "TRANSPARENT_SHARED_ARTIFACT_BUS",
        },
    }
    packet["next_focus"] = _focus(frontier, pr_summary, counterexamples, owned)

    stable = dict(packet)
    stable.pop("generated_at_utc", None)
    packet["digest"] = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    frontier = packet["external_frontier"]
    owned = packet["owned_range_active"]
    swarm = packet["pr_swarm"]
    examples = packet["adversary_counterexamples"]
    lines = [
        "## SENJU AGENCY BUS",
        "",
        f"agency-digest: `{packet['digest']}`",
        f"next-focus: `{packet['next_focus']}`",
        "",
        f"- frontier: {frontier['successful_steps']}/{frontier['steps_executed']} successful, {len(frontier['contacted_hosts'])} contacted hosts, {frontier['discovered_links_enqueued']} links enqueued",
        f"- owned range: {'present' if owned['present'] else 'missing'} / requests {owned['request_count']} / pages {owned['pages_discovered']} / writes {owned['write_attempts']} / ACK {owned['write_provider_acks']} / readback {owned['independent_readbacks']} / counterexamples {owned['counterexample_count']}",
        f"- PR swarm: {swarm['senju_related']} Senju-related / {swarm['open_senju']} open / BLOCK {swarm['audit_blocked']} / WAIT {swarm['audit_waiting']} / PASS+MERGED {swarm['audit_passed']}",
        f"- combined counterexamples: {len(examples)}",
        f"- evolution safe: {packet['evolution']['safe']} / covenant: {packet['evolution']['covenant_mode']}",
        "",
        "### Evolving owned-range probe ranking",
    ]
    if owned["next_family_ranking"]:
        lines.append("- " + " -> ".join(f"`{x}`" for x in owned["next_family_ranking"][:8]))
    else:
        lines.append("- no owned-range memory restored yet")
    lines += ["", "### Counterexample feed"]
    if examples:
        for row in examples[:16]:
            label = row.get("surface") or row.get("target") or row.get("path") or row.get("probe") or row.get("source")
            reason = row.get("reason") or row.get("error") or row.get("message") or row.get("outcome") or "observed"
            lines.append(f"- `{row['kind']}` {str(label)[:160]} — {str(reason)[:240]}")
    else:
        lines.append("- no new adversarial counterexample in the restored evidence")
    lines += [
        "",
        "### Contract",
        "Public web discovery is read-only. The explicitly owned range may receive bounded same-origin non-destructive active probes and dummy writes with readback. Repository/owned effects and AI delegation may act autonomously; unauthorized third-party writes and live guard bypass are not execution surfaces.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frontier", required=True)
    ap.add_argument("--evolution", required=True)
    ap.add_argument("--prs", required=True)
    ap.add_argument("--pr273")
    ap.add_argument("--pr275")
    ap.add_argument("--merge-audit")
    ap.add_argument("--owned-range")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown", required=True)
    args = ap.parse_args()

    packet = build_bus(
        _load_json(args.frontier, {}),
        _load_json(args.evolution, {}),
        _load_json(args.prs, []),
        pr273_root=args.pr273,
        pr275_root=args.pr275,
        merge_audit=_load_json(args.merge_audit, {}),
        owned_range=_load_json(args.owned_range, {}),
    )
    Path(args.out).write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.markdown).write_text(render_markdown(packet), encoding="utf-8")
    print(json.dumps({"digest": packet["digest"], "focus": packet["next_focus"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
