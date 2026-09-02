"""Autonomous external-observation loop for Senju + RED.

The director is allowed to decide *when* and *which registered observation mission*
to run without a per-cycle human instruction. Authority remains data-driven: every
URL must belong to either a built-in public-research scope or an explicitly supplied
registry scope. The autonomous lane is read-only (GET/HEAD/OPTIONS).

This gives RED initiative over external observation without turning target discovery
into arbitrary Internet scanning. RED priorities influence mission selection; real
contact receipts feed the next cycle's mission memory and handoff evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .external import (
    BUILTIN_AUTHORITY_SCOPES,
    ContactResult,
    ExternalAuthorityScope,
    ExternalContactClient,
    ExternalContactError,
)

REGISTRY_SCHEMA = "senju-autonomous-contact-registry/v1"
REPORT_SCHEMA = "senju-autonomous-contact-report/v1"
MEMORY_SCHEMA = "senju-autonomous-contact-memory/v1"
READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class ContactMission:
    mission_id: str
    scope_id: str
    url: str
    method: str
    purpose: str
    base_priority: float = 0.5
    red_tags: tuple[str, ...] = ()
    source: str = "builtin"


@dataclass
class MissionMemory:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_status: int | None = None
    last_response_sha256: str | None = None
    last_contacted_at_utc: str | None = None

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0


@dataclass
class AutonomousContactMemory:
    missions: dict[str, MissionMemory] = field(default_factory=dict)
    cycles: int = 0

    def state(self, mission_id: str) -> MissionMemory:
        return self.missions.setdefault(mission_id, MissionMemory())

    def record_result(self, mission_id: str, result: ContactResult) -> None:
        """Record provider acknowledgement, not merely TCP/HTTP completion, as success."""
        state = self.state(mission_id)
        receipt = result.receipt
        state.attempts += 1
        state.last_status = receipt.status
        state.last_response_sha256 = receipt.response_sha256
        state.last_contacted_at_utc = receipt.contacted_at_utc
        if receipt.provider_acknowledged:
            state.successes += 1
            state.consecutive_failures = 0
        else:
            state.failures += 1
            state.consecutive_failures += 1

    def record_failure(self, mission_id: str) -> None:
        state = self.state(mission_id)
        state.attempts += 1
        state.failures += 1
        state.consecutive_failures += 1
        state.last_contacted_at_utc = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MEMORY_SCHEMA,
            "cycles": self.cycles,
            "missions": {
                key: asdict(value) | {"success_rate": round(value.success_rate, 4)}
                for key, value in sorted(self.missions.items())
            },
        }

    @staticmethod
    def from_mapping(data: Mapping[str, Any] | None) -> "AutonomousContactMemory":
        if not data or data.get("schema") != MEMORY_SCHEMA:
            return AutonomousContactMemory()
        out = AutonomousContactMemory(cycles=max(0, int(data.get("cycles", 0))))
        raw_missions = data.get("missions") or {}
        if isinstance(raw_missions, Mapping):
            for key, raw in raw_missions.items():
                if not isinstance(raw, Mapping):
                    continue
                allowed = {name for name in MissionMemory.__dataclass_fields__}
                body = {name: raw[name] for name in allowed if name in raw}
                out.missions[str(key)] = MissionMemory(**body)
        return out


BUILTIN_MISSIONS: tuple[ContactMission, ...] = (
    ContactMission(
        mission_id="public-nvd-pulse",
        scope_id="threat_intel_public",
        url="https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=1",
        method="GET",
        purpose="sample current public vulnerability telemetry for RED research context",
        base_priority=0.92,
        red_tags=("misconfig", "auth_bypass", "secrets_exposure"),
    ),
    ContactMission(
        mission_id="public-github-runtime-pulse",
        scope_id="github_metadata",
        url="https://api.github.com/repos/cli/cli/releases/latest",
        method="GET",
        purpose="sample public software-release metadata for external-change awareness",
        base_priority=0.68,
        red_tags=("supply_chain", "misconfig"),
    ),
    ContactMission(
        mission_id="public-egress-canary",
        scope_id="canary_telemetry",
        url="https://example.com/",
        method="GET",
        purpose="prove live outbound transport remains operational",
        base_priority=0.58,
        red_tags=("external_observation",),
    ),
)


def _normalize_method(raw: Any) -> str:
    method = str(raw or "GET").upper().strip()
    if method not in READ_ONLY_METHODS:
        raise ValueError(f"autonomous contact is read-only; method not allowed: {method}")
    return method


def _host(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError(f"invalid HTTP(S) mission URL: {url!r}")
    return parsed.hostname.lower().rstrip(".")


def _scope_from_mapping(data: Mapping[str, Any]) -> ExternalAuthorityScope:
    scope_id = str(data.get("scope_id") or "").strip()
    hosts = frozenset(str(x).strip().lower().rstrip(".") for x in (data.get("allow_hosts") or []) if str(x).strip())
    if not scope_id or not hosts:
        raise ValueError("registry authority scope requires scope_id and allow_hosts")
    methods = frozenset(_normalize_method(x) for x in (data.get("allowed_methods") or ["GET", "HEAD"]))
    return ExternalAuthorityScope(
        scope_id=scope_id,
        target_service=str(data.get("target_service") or scope_id),
        allow_hosts=hosts,
        allowed_methods=methods,
        allow_http=bool(data.get("allow_http", False)),
        allow_delete=False,
        rate_limit_per_minute=max(1, min(int(data.get("rate_limit_per_minute", 12)), 60)),
        timeout_seconds=max(1.0, min(float(data.get("timeout_seconds", 8.0)), 20.0)),
        max_request_bytes=0,
        max_response_bytes=max(1024, min(int(data.get("max_response_bytes", 512 * 1024)), 4 * 1024 * 1024)),
        retries=max(0, min(int(data.get("retries", 1)), 3)),
        follow_redirects=bool(data.get("follow_redirects", True)),
        credential_scope="none",
        verification_strategy="sha256_receipt",
        rollback_supported=False,
        description=str(data.get("description") or "explicit autonomous observation scope"),
    )


def load_registry(value: Mapping[str, Any] | None) -> tuple[list[ContactMission], dict[str, ExternalAuthorityScope]]:
    if not value:
        return [], {}
    if value.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"registry schema must be {REGISTRY_SCHEMA}")

    scopes: dict[str, ExternalAuthorityScope] = {}
    for raw in value.get("scopes") or []:
        if not isinstance(raw, Mapping):
            raise ValueError("registry scopes must be objects")
        scope = _scope_from_mapping(raw)
        if scope.scope_id in BUILTIN_AUTHORITY_SCOPES or scope.scope_id in scopes:
            raise ValueError(f"duplicate/reserved scope id: {scope.scope_id}")
        scopes[scope.scope_id] = scope

    missions: list[ContactMission] = []
    seen: set[str] = set()
    for raw in value.get("missions") or []:
        if not isinstance(raw, Mapping):
            raise ValueError("registry missions must be objects")
        mission_id = str(raw.get("mission_id") or "").strip()
        scope_id = str(raw.get("scope_id") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not mission_id or mission_id in seen:
            raise ValueError(f"mission_id missing or duplicated: {mission_id!r}")
        seen.add(mission_id)
        scope = scopes.get(scope_id) or BUILTIN_AUTHORITY_SCOPES.get(scope_id)
        if scope is None:
            raise ValueError(f"unknown authority scope: {scope_id}")
        host = _host(url)
        if host not in scope.allow_hosts:
            raise ValueError(f"mission host {host!r} is outside authority scope {scope_id!r}")
        method = _normalize_method(raw.get("method"))
        if method not in scope.allowed_methods:
            raise ValueError(f"mission method {method} is outside authority scope {scope_id!r}")
        tags = tuple(str(x).strip() for x in (raw.get("red_tags") or []) if str(x).strip())
        missions.append(ContactMission(
            mission_id=mission_id,
            scope_id=scope_id,
            url=url,
            method=method,
            purpose=str(raw.get("purpose") or "autonomous authorized observation"),
            base_priority=max(0.0, min(float(raw.get("base_priority", 0.5)), 1.0)),
            red_tags=tags,
            source="registry",
        ))
    return missions, scopes


def load_red_priorities(data: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not data:
        return ()
    raw = data.get("priority_next") or []
    if not isinstance(raw, list):
        return ()
    return tuple(dict.fromkeys(str(x).strip() for x in raw if str(x).strip()))


class AutonomousContactDirector:
    """Let RED/Senju choose the next registered external observation mission."""

    def __init__(self, *, max_missions_per_cycle: int = 3) -> None:
        self.max_missions_per_cycle = max(1, min(int(max_missions_per_cycle), 8))

    def score(
        self,
        mission: ContactMission,
        memory: AutonomousContactMemory,
        red_priorities: Iterable[str] = (),
    ) -> tuple[float, tuple[str, ...]]:
        state = memory.state(mission.mission_id)
        priorities = set(red_priorities)
        score = 0.55 + 0.9 * mission.base_priority
        reasons = ["self-initiated"]
        if state.attempts == 0:
            score += 0.75
            reasons.append("never-observed")
        else:
            score += max(0.0, 0.35 - 0.04 * state.attempts)
        matched = priorities.intersection(mission.red_tags)
        if matched:
            score += min(0.8, 0.22 * len(matched))
            reasons.append("red-priority:" + ",".join(sorted(matched)))
        if state.consecutive_failures:
            score += min(0.35, 0.08 * state.consecutive_failures)
            reasons.append("retry-for-resilience")
        if state.success_rate > 0.9 and state.attempts >= 4:
            score -= 0.18
            reasons.append("well-observed")
        return round(max(0.0, score), 4), tuple(reasons)

    def plan(
        self,
        missions: Sequence[ContactMission],
        memory: AutonomousContactMemory,
        *,
        red_priorities: Iterable[str] = (),
        seed: int | None = None,
    ) -> list[dict[str, Any]]:
        if not missions:
            raise ValueError("at least one autonomous contact mission is required")
        rng = random.Random(seed)
        ranked: list[tuple[float, float, ContactMission, tuple[str, ...]]] = []
        for mission in missions:
            score, reasons = self.score(mission, memory, red_priorities)
            ranked.append((score, rng.random(), mission, reasons))
        ranked.sort(key=lambda row: (-row[0], row[1], row[2].mission_id))
        return [
            {
                "rank": index,
                "score": score,
                "reasons": list(reasons),
                "mission": asdict(mission),
            }
            for index, (score, _, mission, reasons) in enumerate(
                ranked[: self.max_missions_per_cycle], start=1
            )
        ]


def _scope_for(mission: ContactMission, custom_scopes: Mapping[str, ExternalAuthorityScope]) -> ExternalAuthorityScope:
    scope = custom_scopes.get(mission.scope_id) or BUILTIN_AUTHORITY_SCOPES.get(mission.scope_id)
    if scope is None:
        raise ValueError(f"authority scope disappeared: {mission.scope_id}")
    if _host(mission.url) not in scope.allow_hosts:
        raise ValueError(f"mission host is outside authority scope: {mission.mission_id}")
    if mission.method not in READ_ONLY_METHODS or mission.method not in scope.allowed_methods:
        raise ValueError(f"mission method is outside autonomous read-only authority: {mission.mission_id}")
    return scope


def run_cycle(
    *,
    registry: Mapping[str, Any] | None = None,
    memory_data: Mapping[str, Any] | None = None,
    red_data: Mapping[str, Any] | None = None,
    max_missions: int = 3,
    seed: int = 20260830,
    client_factory: Callable[[ExternalAuthorityScope], ExternalContactClient] | None = None,
) -> dict[str, Any]:
    registry_missions, custom_scopes = load_registry(registry)
    missions = list(BUILTIN_MISSIONS) + registry_missions
    memory = AutonomousContactMemory.from_mapping(memory_data)
    red_priorities = load_red_priorities(red_data)
    director = AutonomousContactDirector(max_missions_per_cycle=max_missions)
    plan = director.plan(missions, memory, red_priorities=red_priorities, seed=seed + memory.cycles)

    observations: list[dict[str, Any]] = []
    for item in plan:
        mission = ContactMission(**item["mission"])
        scope = _scope_for(mission, custom_scopes)
        client = client_factory(scope) if client_factory else ExternalContactClient(scope.to_policy())
        try:
            result = client.contact_with_body(mission.url, method=mission.method)
        except (ExternalContactError, OSError, TimeoutError) as exc:
            memory.record_failure(mission.mission_id)
            observations.append({
                "mission_id": mission.mission_id,
                "scope_id": mission.scope_id,
                "purpose": mission.purpose,
                "success": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })
            continue
        memory.record_result(mission.mission_id, result)
        observations.append({
            "mission_id": mission.mission_id,
            "scope_id": mission.scope_id,
            "purpose": mission.purpose,
            "success": bool(result.receipt.provider_acknowledged),
            "receipt": result.receipt.to_dict(),
        })

    memory.cycles += 1
    acknowledged = sum(1 for x in observations if x.get("success"))
    return {
        "schema": REPORT_SCHEMA,
        "cycle_id": f"autocontact-{uuid.uuid4().hex[:12]}",
        "executed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "doctrine": "RED_INITIATIVE_EXTERNAL_OBSERVATION",
        "self_initiated": True,
        "network_io": True,
        "per_cycle_human_instruction_required": False,
        "authority_is_registry_or_builtin": True,
        "arbitrary_target_discovery": False,
        "autonomous_effect": "read-only",
        "red_priorities": list(red_priorities),
        "planned": plan,
        "observations": observations,
        "provider_acknowledged": acknowledged,
        "attempted": len(observations),
        "memory": memory.to_dict(),
        "red_handoff": {
            "schema": "senju-autonomous-contact-red-handoff/v1",
            "external_observations": [
                {
                    "mission_id": x["mission_id"],
                    "scope_id": x["scope_id"],
                    "success": x["success"],
                    "status": (x.get("receipt") or {}).get("status"),
                    "response_sha256": (x.get("receipt") or {}).get("response_sha256"),
                }
                for x in observations
            ],
            "priority_next": list(red_priorities),
            "instruction": "use real external change/availability evidence to choose the next Arena or authorized-lab research pressure; do not infer exploitability from transport success",
        },
    }


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    value = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {p}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Senju self-initiated external observation cycle")
    parser.add_argument("--registry")
    parser.add_argument("--memory")
    parser.add_argument("--red-research")
    parser.add_argument("--out", required=True)
    parser.add_argument("--memory-out")
    parser.add_argument("--max-missions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260830)
    args = parser.parse_args(argv)

    report = run_cycle(
        registry=_read_json(args.registry),
        memory_data=_read_json(args.memory),
        red_data=_read_json(args.red_research),
        max_missions=args.max_missions,
        seed=args.seed,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    memory_out = Path(args.memory_out) if args.memory_out else out.with_name("autonomous-contact-memory.json")
    memory_out.parent.mkdir(parents=True, exist_ok=True)
    memory_out.write_text(json.dumps(report["memory"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "SENJU_AUTONOMOUS_EXTERNAL_CONTACT "
        f"attempted={report['attempted']} acknowledged={report['provider_acknowledged']} "
        f"human_instruction_required={str(report['per_cycle_human_instruction_required']).lower()}"
    )
    return 0 if report["provider_acknowledged"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
