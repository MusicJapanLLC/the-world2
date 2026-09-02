#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass
class Check:
    target_id: str
    name: str
    url: str
    declared_priority: str
    ok: bool
    status: int | None
    latency_ms: int | None
    bytes_read: int
    health_url: str | None
    health_ok: bool | None
    health_status: int | None
    health_latency_ms: int | None
    error: str | None
    score: int


def _probe(url: str, timeout: float = 15.0) -> tuple[bool, int | None, int, int, str | None]:
    started = time.perf_counter()
    req = request.Request(
        url,
        headers={
            "User-Agent": "THE-WORLD-Portfolio-Forge/2.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as res:
            body = res.read(512_000)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return True, int(getattr(res, "status", 200)), latency_ms, len(body), None
    except error.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            body = exc.read(512_000)
        except Exception:
            body = b""
        return True, int(exc.code), latency_ms, len(body), f"HTTPError:{exc.code}"
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return False, None, latency_ms, 0, type(exc).__name__


def fetch_target(target: dict[str, Any]) -> Check:
    target_id = str(target.get("id") or target.get("name") or "unknown-target")
    name = str(target.get("name") or target_id)
    url = str(target["url"])
    expected = {int(v) for v in (target.get("expected_status") or [200, 301, 302, 307, 308])}
    budget_ms = max(250, int(target.get("latency_budget_ms") or 3000))
    declared_priority = str(target.get("priority") or "P2")

    reachable, status, latency_ms, bytes_read, probe_error = _probe(url)
    homepage_ok = bool(reachable and status in expected and bytes_read > 200)

    health_url = str(target.get("health_url") or "") or None
    health_ok: bool | None = None
    health_status: int | None = None
    health_latency_ms: int | None = None
    health_error: str | None = None
    if health_url:
        health_reachable, health_status, health_latency_ms, _health_bytes, health_error = _probe(health_url)
        health_ok = bool(health_reachable and health_status in expected)

    ok = homepage_ok and health_ok is not False
    score = 100 if homepage_ok else 0
    if homepage_ok:
        if latency_ms > budget_ms * 2:
            score -= 30
        elif latency_ms > budget_ms:
            score -= 18
        elif latency_ms > int(budget_ms * 0.7):
            score -= 8
        if bytes_read < 1500:
            score -= 10
        if health_ok is False:
            score -= 60
        elif health_ok is True and health_latency_ms is not None:
            if health_latency_ms > budget_ms * 2:
                score -= 20
            elif health_latency_ms > budget_ms:
                score -= 10

    errors = [x for x in (probe_error if not homepage_ok else None, health_error if health_ok is False else None) if x]
    return Check(
        target_id=target_id,
        name=name,
        url=url,
        declared_priority=declared_priority,
        ok=ok,
        status=status,
        latency_ms=latency_ms,
        bytes_read=bytes_read,
        health_url=health_url,
        health_ok=health_ok,
        health_status=health_status,
        health_latency_ms=health_latency_ms,
        error=";".join(errors) if errors else None,
        score=max(0, score),
    )


def priority(check: Check) -> str:
    if not check.ok:
        return "P0 production health" if check.declared_priority == "P0" else "P1 production health"
    if check.score < 70:
        return "P2 reliability/performance"
    if check.score < 90:
        return "P6 performance/UX"
    return "HEALTHY"


def _incident_fingerprint(checks: list[Check]) -> str:
    material: list[dict[str, Any]] = []
    for c in checks:
        if c.ok and c.score >= 90:
            continue
        score_band = "fail" if not c.ok else ("lt70" if c.score < 70 else "lt90")
        material.append(
            {
                "id": c.target_id,
                "declared_priority": c.declared_priority,
                "status": c.status,
                "health_status": c.health_status,
                "score_band": score_band,
                "error": c.error,
            }
        )
    if not material:
        return "healthy"
    raw = json.dumps(sorted(material, key=lambda x: x["id"]), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _focus_key(check: Check) -> tuple[int, int, int, str]:
    declared = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(check.declared_priority, 4)
    health = 0 if not check.ok else 1
    return health, declared, check.score, check.target_id


def build_report(checks: list[Check]) -> dict[str, Any]:
    avg = round(sum(c.score for c in checks) / len(checks), 1) if checks else 0.0
    failures = [c for c in checks if not c.ok]
    degraded = [c for c in checks if c.ok and c.score < 90]
    weakest = sorted(checks, key=_focus_key)[0] if checks else None
    fingerprint = _incident_fingerprint(checks)
    return {
        "schema": "the-world.portfolio-watch.v2",
        "generated_at_epoch": int(time.time()),
        "portfolio_score": avg,
        "healthy": len(checks) - len(failures) - len(degraded),
        "degraded": len(degraded),
        "failed": len(failures),
        "incident_fingerprint": fingerprint,
        "checks": [asdict(c) | {"priority": priority(c)} for c in checks],
        "next_focus": (
            {
                "id": weakest.target_id,
                "name": weakest.name,
                "url": weakest.url,
                "priority": priority(weakest),
                "declared_priority": weakest.declared_priority,
                "reason": weakest.error
                or (
                    f"score={weakest.score}, latency_ms={weakest.latency_ms}, "
                    f"health_ok={weakest.health_ok}, health_status={weakest.health_status}"
                ),
            }
            if weakest
            else None
        ),
        "material_delta": fingerprint != "healthy",
        "claim_boundary": (
            "Production GET/health evidence only. A healthy probe is not proof that every AI action works; "
            "golden-path action verification is still required before claiming capability improvement."
        ),
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# THE WORLD Portfolio Forge — Live Evidence",
        "",
        f"- portfolio score: **{report['portfolio_score']} / 100**",
        f"- healthy: **{report['healthy']}**",
        f"- degraded: **{report['degraded']}**",
        f"- failed: **{report['failed']}**",
        f"- incident fingerprint: `{report['incident_fingerprint']}`",
        "",
        "## Live checks",
    ]
    for c in report["checks"]:
        icon = "✅" if c["ok"] and c["score"] >= 90 else ("⚠️" if c["ok"] else "❌")
        health = "" if c["health_ok"] is None else f" / health={c['health_ok']}({c['health_status']})"
        lines.append(
            f"- {icon} **{c['name']}** — status={c['status']} / latency={c['latency_ms']}ms{health} / "
            f"score={c['score']} / {c['priority']}"
        )
    nf = report.get("next_focus")
    if nf:
        lines += [
            "",
            "## Next highest-value focus",
            f"- product: **{nf['name']}**",
            f"- priority: **{nf['priority']}**",
            f"- reason: `{nf['reason']}`",
            f"- live: {nf['url']}",
        ]
    lines += ["", f"> {report['claim_boundary']}"]
    return "\n".join(lines) + "\n"


def load_targets(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    targets = payload.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise ValueError("portfolio target registry has no targets")
    return [dict(row) for row in targets]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="automation/reporting/portfolio_targets.json")
    p.add_argument("--json", default="portfolio-watch.json")
    p.add_argument("--markdown", default="portfolio-watch.md")
    args = p.parse_args()

    checks = [fetch_target(target) for target in load_targets(args.registry)]
    report = build_report(checks)
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.markdown).write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    # Detector execution succeeded even when the target is unhealthy. Target health is data, not detector health.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
