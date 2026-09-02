from __future__ import annotations

from senju.autonomous_contact import (
    AutonomousContactDirector,
    AutonomousContactMemory,
    BUILTIN_MISSIONS,
    REGISTRY_SCHEMA,
    load_registry,
    run_cycle,
)
from senju.external import ContactReceipt, ContactResult


def test_red_priority_increases_matching_external_mission_pressure() -> None:
    director = AutonomousContactDirector(max_missions_per_cycle=3)
    memory = AutonomousContactMemory()
    plain = director.plan(BUILTIN_MISSIONS, memory, red_priorities=(), seed=7)
    boosted = director.plan(BUILTIN_MISSIONS, memory, red_priorities=("supply_chain",), seed=7)
    plain_score = next(x["score"] for x in plain if x["mission"]["mission_id"] == "public-github-runtime-pulse")
    boosted_score = next(x["score"] for x in boosted if x["mission"]["mission_id"] == "public-github-runtime-pulse")
    assert boosted_score > plain_score


def test_registry_cannot_smuggle_host_outside_declared_scope() -> None:
    registry = {
        "schema": REGISTRY_SCHEMA,
        "scopes": [
            {
                "scope_id": "owned-app",
                "target_service": "owned app",
                "allow_hosts": ["owned.example.test"],
                "allowed_methods": ["GET"],
            }
        ],
        "missions": [
            {
                "mission_id": "escape",
                "scope_id": "owned-app",
                "url": "https://different.example.test/",
                "method": "GET",
            }
        ],
    }
    try:
        load_registry(registry)
    except ValueError as exc:
        assert "outside authority scope" in str(exc)
    else:
        raise AssertionError("out-of-scope mission was accepted")


def test_autonomous_registry_rejects_write_method() -> None:
    registry = {
        "schema": REGISTRY_SCHEMA,
        "scopes": [
            {
                "scope_id": "owned-app",
                "target_service": "owned app",
                "allow_hosts": ["owned.example.test"],
                "allowed_methods": ["POST"],
            }
        ],
        "missions": [],
    }
    try:
        load_registry(registry)
    except ValueError as exc:
        assert "read-only" in str(exc)
    else:
        raise AssertionError("autonomous write authority was accepted")


class _FakeClient:
    acknowledged = True
    status = 200

    def __init__(self, scope) -> None:  # noqa: ANN001
        self.scope = scope

    def contact_with_body(self, url: str, *, method: str = "GET") -> ContactResult:
        host = url.split("/", 3)[2]
        receipt = ContactReceipt(
            schema="senju-external-contact/v1",
            contacted_at_utc="2026-08-30T14:00:00+00:00",
            method=method,
            requested_url=url,
            final_url=url,
            host=host,
            final_host=host,
            contacted_hosts=(host,),
            resolved_ips=("203.0.113.10",),
            status=self.status,
            provider_acknowledged=self.acknowledged,
            response_bytes=2,
            response_sha256="a" * 64,
            content_type="application/json",
            etag=None,
            last_modified=None,
            retry_after=None,
            attempt_count=1,
            redirect_count=0,
        )
        return ContactResult(receipt=receipt, body=b"{}")


class _FakeNonAckClient(_FakeClient):
    acknowledged = False
    status = 404


def test_cycle_is_self_initiated_and_emits_red_handoff_without_live_network() -> None:
    report = run_cycle(
        red_data={"priority_next": ["supply_chain", "misconfig"]},
        max_missions=2,
        seed=11,
        client_factory=_FakeClient,
    )
    assert report["self_initiated"] is True
    assert report["per_cycle_human_instruction_required"] is False
    assert report["network_io"] is True
    assert report["autonomous_effect"] == "read-only"
    assert report["attempted"] == 2
    assert report["provider_acknowledged"] == 2
    assert len(report["red_handoff"]["external_observations"]) == 2


def test_non_acknowledged_http_response_is_failure_memory() -> None:
    report = run_cycle(max_missions=1, seed=3, client_factory=_FakeNonAckClient)
    assert report["provider_acknowledged"] == 0
    mission_id = report["planned"][0]["mission"]["mission_id"]
    state = report["memory"]["missions"][mission_id]
    assert state["attempts"] == 1
    assert state["successes"] == 0
    assert state["failures"] == 1
    assert state["consecutive_failures"] == 1
