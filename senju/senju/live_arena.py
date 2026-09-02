"""Live external observation -> Senju RED/BLUE arena evolution.

This module deliberately joins the previously separate external-contact and arena
loops. Senju performs a real bounded GET/HEAD request, converts the response into
an ObservedExternalTarget, then runs the normal evolutionary tournament against
that target landscape.

Read-only observation is frictionless: the public hostname contained in the URL
is automatically added to the observation allowlist. Callers may still add extra
hosts as one bundled read scope (for example related API/CDN hosts). This automatic
authorization applies only to GET/HEAD observation; it does not grant write or
exploit authority.

The real network action is observation only. RED/BLUE capture/block events remain
in-process simulation and are never emitted as exploit traffic.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import urllib.parse
from pathlib import Path
from typing import Iterable

from .config import ArenaConfig, EvolutionConfig, SenjuConfig
from .external import ExternalContactClient, ExternalContactPolicy
from .targets.observed import ObservedExternalTarget
from .tournament import Tournament, TournamentReport


class LiveObservedTournament(Tournament):
    """Tournament whose target landscape is anchored to one live HTTP observation."""

    def __init__(self, config: SenjuConfig, receipt, source_url: str) -> None:  # noqa: ANN001
        self._live_receipt = receipt
        self._live_source_url = source_url
        super().__init__(config)

    def _make_target(self, idx: int) -> ObservedExternalTarget:
        return ObservedExternalTarget(
            self._live_receipt,
            self._live_source_url,
            instance=idx,
            n_surfaces=8,
        )


def _champion_summary(agent) -> dict[str, object] | None:  # noqa: ANN001
    if agent is None:
        return None
    return {
        "agent_id": agent.agent_id,
        "side": agent.side,
        "rating": agent.rating,
        "resources": agent.resources,
        "generation": agent.generation,
        "alive": agent.alive,
    }


def _report_summary(report: TournamentReport) -> dict[str, object]:
    return {
        "scenario": report.scenario,
        "generations": [dataclasses.asdict(g) for g in report.generations],
        "red_champion": _champion_summary(report.red_champion),
        "blue_champion": _champion_summary(report.blue_champion),
        "scope_violations": report.scope_violations,
    }


def readonly_observation_hosts(
    url: str,
    extra_hosts: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Build the read scope from the URL plus any caller-supplied companion hosts.

    The URL hostname is automatically authorized for read-only observation. This
    removes the old requirement to repeat ``--allow-host`` for the site being read.
    Extra hosts are merged into the same observation scope for related public
    endpoints while the external transport still performs its normal DNS checks.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"https", "http"}:
        raise ValueError("live arena observation requires an http/https URL")
    if not parsed.hostname:
        raise ValueError("live arena observation URL has no hostname")

    hosts = {parsed.hostname.rstrip(".").lower()}
    for host in extra_hosts or ():
        value = str(host).strip().rstrip(".").lower()
        if value:
            hosts.add(value)
    return tuple(sorted(hosts))


def run_live_arena(
    url: str,
    allow_hosts: Iterable[str] | None,
    config: SenjuConfig,
    *,
    method: str = "GET",
    timeout_seconds: float = 5.0,
    retries: int = 1,
    client: ExternalContactClient | None = None,
) -> dict[str, object]:
    method = method.upper().strip()
    if method not in {"GET", "HEAD"}:
        raise ValueError("live arena observation permits GET/HEAD only")

    read_hosts = readonly_observation_hosts(url, allow_hosts)
    policy = ExternalContactPolicy.from_hosts(
        read_hosts,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    contact_client = client or ExternalContactClient(policy)
    result = contact_client.contact_with_body(url, method=method)

    prototype = ObservedExternalTarget(result.receipt, url, instance=0)
    tournament = LiveObservedTournament(config, result.receipt, url)
    report = tournament.run()

    return {
        "schema": "senju-live-observation-arena/v1",
        "coupling": {
            "real_external_observation": True,
            "observation_influences_arena_target": True,
            "arena_influences_evolution": True,
            "external_method": method,
            "read_host_auto_authorized": True,
            "read_scope_hosts": list(read_hosts),
            "real_exploit_traffic": False,
        },
        "observation": result.receipt.to_dict(),
        "observed_target": prototype.evidence(),
        "arena": _report_summary(report),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run Senju evolution on a target landscape derived from a live HTTP observation"
    )
    p.add_argument("url")
    p.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="optional companion public host to include in the same read-only observation scope",
    )
    p.add_argument("--method", choices=("GET", "HEAD"), default="GET")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--retries", type=int, default=1)
    p.add_argument("--population", type=int, default=16)
    p.add_argument("--generations", type=int, default=3)
    p.add_argument("--matches", type=int, default=30)
    p.add_argument("--red-budget", type=int, default=12)
    p.add_argument("--blue-budget", type=int, default=12)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out")
    args = p.parse_args(argv)

    config = SenjuConfig(
        scenario_name="live-observed-arena",
        arena=ArenaConfig(
            red_action_budget=args.red_budget,
            blue_action_budget=args.blue_budget,
            seed=args.seed,
        ),
        evolution=EvolutionConfig(
            population_size=max(4, args.population),
            generations=max(1, args.generations),
            matches_per_generation=max(1, args.matches),
            seed=args.seed,
        ),
    )
    evidence = run_live_arena(
        args.url,
        args.allow_host,
        config,
        method=args.method,
        timeout_seconds=args.timeout,
        retries=args.retries,
    )
    text = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())