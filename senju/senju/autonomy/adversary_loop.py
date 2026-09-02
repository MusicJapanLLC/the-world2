"""Persistent Senju autonomy loop for adversarial pressure on real guard surfaces.

This module bridges the repository's real-surface adversary harness into Senju's
persistent autonomy state. External side effects stay disabled: pressure is
applied through local fault injection, malformed inputs, controlled transport
seams, and the real guard implementations exercised by
``senju.real_surface_adversary``.

Every controlled attack that produces an observable availability effect is
streamed into Senju immediately. A durable JSONL event is written, one red-team
WorkItem is placed onto the real main AutonomyEngine queue, and Senju executes a
bounded number of adjacent-family follow-ups during the same pressure round.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from .engine import AutonomyEngine
from .queue import AutonomyQueue, WorkItem
from ..real_surface_adversary import run as run_real_surface_adversary


@dataclasses.dataclass(frozen=True)
class AdversaryCycleResult:
    item_id: str
    status: str
    rounds: int
    probes_run: int
    failed_probes: int
    failed_targets: tuple[str, ...]
    failure_fingerprint: str
    report_path: str
    proposed_next_items: tuple[str, ...]
    effective_attacks: int
    senju_shared_events: int
    senju_joined_cycles: int
    event_log_path: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class SenjuAdversaryLoop:
    """Drive repeated real-surface fault injection from Senju autonomy state."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Real Senju engine and its real persistent queue.
        self.engine = AutonomyEngine(self.state_dir)

        # Keep raw pressure scheduling separate from the main tournament/autonomy
        # queue. Effective attack evidence is intentionally bridged into the main
        # queue below so Senju itself joins the follow-up.
        self.queue = AutonomyQueue(self.state_dir / "real_surface_adversary_queue.json")
        self.report_dir = self.state_dir / "autonomy_reports" / "real_surface_adversary"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.event_log = self.report_dir / "attack_effects.jsonl"

    @staticmethod
    def _stamp() -> str:
        return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")

    def _enqueue_fresh_cycle(self, *, rounds: int) -> str:
        stamp = self._stamp()
        item = WorkItem(
            item_id=f"real-surface-pressure-{stamp}",
            hypothesis=(
                "Repeated real-repository fault injection should expose guard regressions "
                "before they escape Senju CI or autonomy state"
            ),
            category="security",
            expected_value=0.99,
            cost_budget_matches=25,
            runtime_seconds_budget=300.0,
            max_retries=4,
            authority_scope="none",
            parameters={
                "runner": "real_surface_adversary",
                "rounds": rounds,
                "pressure_mode": "repo-local-fault-injection",
                "cycle_nonce": stamp,
            },
        )
        if not self.queue.enqueue(item):
            raise RuntimeError("failed to enqueue a unique adversary pressure cycle")
        return item.item_id

    @staticmethod
    def _failed_rows(report: dict[str, object]) -> list[dict[str, object]]:
        rows = report.get("results", [])
        if not isinstance(rows, list):
            return [{"target": "report", "name": "invalid-results", "detail": "results is not a list"}]
        return [
            row
            for row in rows
            if isinstance(row, dict) and row.get("passed") is not True
        ]

    @staticmethod
    def _failure_fingerprint(failures: list[dict[str, object]]) -> str:
        normalized = [
            {
                "target": str(row.get("target", "unknown")),
                "name": str(row.get("name", "unknown")),
                "detail": str(row.get("detail", "")),
            }
            for row in failures
        ]
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:20]

    @staticmethod
    def _effect_class(row: dict[str, object]) -> tuple[str, str] | None:
        """Classify controlled attacks that actually interrupt a guarded lane.

        These are not claims of compromise. They are observable fail-closed
        availability effects created inside the repository-local adversary lab.
        """
        if row.get("passed") is not True:
            return None
        target = str(row.get("target", ""))
        name = str(row.get("name", ""))

        if name.startswith("reject-"):
            impact = {
                "engagement-json": "assessment-plan-denied",
                "external-contact": "external-contact-denied-before-io",
                "autonomy-engine": "autonomy-operation-denied",
            }.get(target)
            if impact:
                return impact, "reject-"
        if target == "artifact-guard" and name.startswith("block-"):
            return "release-artifact-gate-blocked", "block-"
        if target == "autonomy-engine" and name == "ignore-corrupt-persisted-state":
            return "persisted-autonomy-queue-dropped", "ignore-corrupt"
        return None

    def _effective_attack_events(
        self,
        report: dict[str, object],
        *,
        pressure_item_id: str,
        round_index: int,
    ) -> list[dict[str, object]]:
        rows = report.get("results", [])
        if not isinstance(rows, list):
            return []
        events: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            classified = self._effect_class(row)
            if classified is None:
                continue
            effect, family = classified
            target = str(row.get("target", "unknown"))
            probe = str(row.get("name", "unknown"))
            detail = str(row.get("detail", ""))
            raw = f"{pressure_item_id}|{round_index}|{target}|{probe}|{detail}".encode("utf-8")
            event_id = hashlib.sha256(raw).hexdigest()[:24]
            events.append(
                {
                    "schema": "senju-adversary-effect/v1",
                    "event_id": event_id,
                    "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "pressure_item_id": pressure_item_id,
                    "pressure_round": round_index,
                    "target": target,
                    "probe": probe,
                    "probe_family": family,
                    "observed_effect": effect,
                    "effect_class": "controlled-availability-impact",
                    "guard_outcome": "fail-closed",
                    "detail": detail,
                }
            )
        return events

    def _share_effect_with_senju(self, event: dict[str, object]) -> str:
        """Persist one attack effect and immediately place it on Senju's main queue."""
        self.event_log.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

        event_id = str(event["event_id"])
        target = str(event["target"])
        probe = str(event["probe"])
        effect = str(event["observed_effect"])
        item = WorkItem(
            item_id=f"adv-effect-{event_id}",
            hypothesis=(
                f"Controlled adversary pressure produced {effect} on {target} via {probe}; "
                "Senju should immediately re-attack the adjacent real-surface probe family"
            ),
            category="red_team",
            expected_value=1.0,
            cost_budget_matches=20,
            runtime_seconds_budget=240.0,
            max_retries=3,
            authority_scope="none",
            prerequisite_evidence=[event_id],
            parameters={
                "runner": "real_surface_followup",
                "focus_target": target,
                "focus_probe": probe,
                "focus_family": str(event.get("probe_family", "")),
                "source_effect_id": event_id,
                "observed_effect": effect,
                "feedback_depth": 0,
            },
        )
        return item.item_id if self.engine.queue.enqueue(item) else ""

    def _senju_join(self, *, max_cycles: int) -> list[dict[str, object]]:
        """Let the actual AutonomyEngine consume bounded adversary feedback now."""
        joined: list[dict[str, object]] = []
        for _ in range(max_cycles):
            result = self.engine.execute_next_cycle(max_matches=20)
            if result is None:
                break
            joined.append(dataclasses.asdict(result))
        return joined

    def _enqueue_followups(
        self,
        *,
        failed_targets: tuple[str, ...],
        fingerprint: str,
        rounds: int,
    ) -> tuple[str, ...]:
        created: list[str] = []
        for target in failed_targets:
            safe_target = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in target)[:48]
            item = WorkItem(
                item_id=f"real-surface-followup-{safe_target}-{fingerprint}",
                hypothesis=(
                    f"Real guard surface {target} failed adversarial pressure; re-run the full "
                    "real-surface suite with elevated repetition until evidence is green"
                ),
                category="security",
                expected_value=1.0,
                cost_budget_matches=25,
                runtime_seconds_budget=360.0,
                max_retries=6,
                authority_scope="none",
                prerequisite_evidence=[fingerprint],
                parameters={
                    "runner": "real_surface_adversary",
                    "rounds": min(rounds + 1, 6),
                    "pressure_mode": "repo-local-fault-injection",
                    "focus_target": target,
                    "failure_fingerprint": fingerprint,
                },
            )
            if self.queue.enqueue(item):
                created.append(item.item_id)
        return tuple(created)

    def run_once(
        self,
        *,
        rounds: int = 2,
        senju_joins_per_round: int = 3,
    ) -> AdversaryCycleResult:
        if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 6:
            raise ValueError("rounds must be an integer between 1 and 6")
        if (
            not isinstance(senju_joins_per_round, int)
            or isinstance(senju_joins_per_round, bool)
            or not 0 <= senju_joins_per_round <= 8
        ):
            raise ValueError("senju_joins_per_round must be an integer between 0 and 8")

        fresh_id = self._enqueue_fresh_cycle(rounds=rounds)
        item = self.queue.select_next(budget_matches=25)
        if item is None:
            raise RuntimeError("adversary queue did not yield a pressure item")
        if item.parameters.get("runner") != "real_surface_adversary":
            self.queue.record_result(
                item.item_id,
                success=False,
                blocker_reason="unexpected runner in dedicated adversary queue",
            )
            raise RuntimeError(f"unexpected adversary runner: {item.parameters.get('runner')!r}")

        requested_rounds = item.parameters.get("rounds", rounds)
        if not isinstance(requested_rounds, int) or isinstance(requested_rounds, bool):
            requested_rounds = rounds
        requested_rounds = max(1, min(requested_rounds, 6))

        round_reports: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        attack_events: list[dict[str, object]] = []
        shared_ids: list[str] = []
        senju_join_results: list[dict[str, object]] = []
        probes_run = 0

        for round_index in range(1, requested_rounds + 1):
            report = dict(run_real_surface_adversary())
            report["pressure_round"] = round_index
            round_reports.append(report)
            try:
                probes_run += int(report.get("total", 0))
            except (TypeError, ValueError):
                pass

            for row in self._failed_rows(report):
                annotated = dict(row)
                annotated["pressure_round"] = round_index
                failures.append(annotated)

            # Share each effective controlled attack as soon as this round observes it.
            round_events = self._effective_attack_events(
                report,
                pressure_item_id=item.item_id,
                round_index=round_index,
            )
            for event in round_events:
                attack_events.append(event)
                queued_id = self._share_effect_with_senju(event)
                if queued_id:
                    shared_ids.append(queued_id)

            # Senju joins during the same round, consuming the highest-priority
            # feedback items from its real main autonomy queue.
            senju_join_results.extend(
                self._senju_join(max_cycles=senju_joins_per_round)
            )

        failed_targets = tuple(sorted({str(row.get("target", "unknown")) for row in failures}))
        fingerprint = self._failure_fingerprint(failures)
        passed = not failures
        followups = self._enqueue_followups(
            failed_targets=failed_targets,
            fingerprint=fingerprint,
            rounds=requested_rounds,
        ) if failures else ()

        timestamp = self._stamp()
        report_path = self.report_dir / f"cycle_{item.item_id}_{timestamp}.json"
        payload = {
            "schema": "senju-adversary-autonomy/v2",
            "mode": "real-repository-surfaces",
            "pressure_mode": "repo-local-fault-injection",
            "item_id": item.item_id,
            "fresh_cycle_id": fresh_id,
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "rounds": requested_rounds,
            "probes_run": probes_run,
            "passed": passed,
            "failed_probes": len(failures),
            "failed_targets": list(failed_targets),
            "failure_fingerprint": fingerprint,
            "proposed_next_items": list(followups),
            "effective_attacks": len(attack_events),
            "senju_shared_events": len(shared_ids),
            "senju_joined_cycles": len(senju_join_results),
            "event_log_path": str(self.event_log),
            "attack_events": attack_events,
            "senju_join_results": senju_join_results,
            "senju_engine": {
                "class": f"{type(self.engine).__module__}.{type(self.engine).__name__}",
                "state_dir": str(self.engine.state_dir),
                "main_queue": str(self.engine.queue.storage_path),
                "main_queue_pending": self.engine.queue.pending_count(),
                "main_queue_completed": self.engine.queue.completed_count(),
            },
            "adversary_queue": {
                "path": str(self.queue.storage_path),
                "pending": self.queue.pending_count(),
                "completed": self.queue.completed_count(),
            },
            "round_reports": round_reports,
        }
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.queue.record_result(
            item.item_id,
            success=passed,
            result_ref=str(report_path) if passed else "",
            blocker_reason=(
                "" if passed else f"{len(failures)} real-surface probe failure(s); fingerprint={fingerprint}"
            ),
        )

        return AdversaryCycleResult(
            item_id=item.item_id,
            status="completed" if passed else "failed",
            rounds=requested_rounds,
            probes_run=probes_run,
            failed_probes=len(failures),
            failed_targets=failed_targets,
            failure_fingerprint=fingerprint,
            report_path=str(report_path),
            proposed_next_items=followups,
            effective_attacks=len(attack_events),
            senju_shared_events=len(shared_ids),
            senju_joined_cycles=len(senju_join_results),
            event_log_path=str(self.event_log),
        )

    def run(
        self,
        *,
        cycles: int = 2,
        rounds_per_cycle: int = 2,
        senju_joins_per_round: int = 3,
    ) -> list[AdversaryCycleResult]:
        if not isinstance(cycles, int) or isinstance(cycles, bool) or not 1 <= cycles <= 8:
            raise ValueError("cycles must be an integer between 1 and 8")
        results: list[AdversaryCycleResult] = []
        for _ in range(cycles):
            results.append(
                self.run_once(
                    rounds=rounds_per_cycle,
                    senju_joins_per_round=senju_joins_per_round,
                )
            )
        return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, default=Path("state"))
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--rounds-per-cycle", type=int, default=2)
    parser.add_argument("--senju-joins-per-round", type=int, default=3)
    parser.add_argument("--json", dest="output", type=Path)
    args = parser.parse_args(argv)

    loop = SenjuAdversaryLoop(args.state_dir)
    results = loop.run(
        cycles=args.cycles,
        rounds_per_cycle=args.rounds_per_cycle,
        senju_joins_per_round=args.senju_joins_per_round,
    )
    rendered_payload = {
        "schema": "senju-adversary-autonomy-summary/v2",
        "passed": all(result.failed_probes == 0 for result in results),
        "cycles": [result.to_dict() for result in results],
        "total_cycles": len(results),
        "total_probes": sum(result.probes_run for result in results),
        "total_failed_probes": sum(result.failed_probes for result in results),
        "total_effective_attacks": sum(result.effective_attacks for result in results),
        "total_senju_shared_events": sum(result.senju_shared_events for result in results),
        "total_senju_joined_cycles": sum(result.senju_joined_cycles for result in results),
    }
    rendered = json.dumps(rendered_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if rendered_payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
