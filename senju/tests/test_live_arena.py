from __future__ import annotations

from senju.config import ArenaConfig, EvolutionConfig, SenjuConfig
from senju.external import ContactReceipt, ContactResult, ExternalContactPolicy
from senju.live_arena import run_live_arena
from senju.targets.observed import ObservedExternalTarget


def _receipt(digest: str = "a" * 64) -> ContactReceipt:
    return ContactReceipt(
        schema="senju-external-contact/v3",
        contacted_at_utc="2026-08-30T12:00:00+00:00",
        method="GET",
        requested_url="https://example.com/",
        final_url="https://example.com/",
        host="example.com",
        final_host="example.com",
        contacted_hosts=("example.com",),
        resolved_ips=("93.184.216.34",),
        status=200,
        provider_acknowledged=True,
        response_bytes=512,
        response_sha256=digest,
        content_type="text/html",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )


class _FakeClient:
    def __init__(self, receipt: ContactReceipt) -> None:
        self.policy = ExternalContactPolicy.from_hosts([receipt.host])
        self._receipt = receipt

    def contact_with_body(self, url: str, *, method: str = "GET", **kwargs):  # noqa: ANN003
        assert url == self._receipt.url
        assert method in {"GET", "HEAD"}
        return ContactResult(receipt=self._receipt, body=b"observed")


def test_observed_target_is_deterministic_for_same_receipt() -> None:
    target = ObservedExternalTarget(_receipt(), "https://example.com/", instance=2)
    first = [(s.vuln_class, s.difficulty) for s in target.surfaces()]
    target.reset()
    second = [(s.vuln_class, s.difficulty) for s in target.surfaces()]
    assert first == second
    assert target.ref.startswith("sim://observed-")
    assert target.evidence()["surfaces_are_simulated_hypotheses"] is True


def test_external_response_fingerprint_changes_arena_landscape() -> None:
    a = ObservedExternalTarget(_receipt("a" * 64), "https://example.com/")
    b = ObservedExternalTarget(_receipt("b" * 64), "https://example.com/")
    assert a.observation_fingerprint != b.observation_fingerprint
    assert [(s.vuln_class, s.difficulty) for s in a.surfaces()] != [
        (s.vuln_class, s.difficulty) for s in b.surfaces()
    ]


def test_live_observation_feeds_normal_tournament() -> None:
    receipt = _receipt()
    config = SenjuConfig(
        scenario_name="test-live",
        arena=ArenaConfig(red_action_budget=4, blue_action_budget=4, seed=7),
        evolution=EvolutionConfig(
            population_size=4,
            generations=1,
            matches_per_generation=3,
            seed=7,
        ),
    )
    evidence = run_live_arena(
        "https://example.com/",
        ["example.com"],
        config,
        client=_FakeClient(receipt),
    )
    assert evidence["schema"] == "senju-live-observation-arena/v1"
    assert evidence["coupling"]["real_external_observation"] is True
    assert evidence["coupling"]["observation_influences_arena_target"] is True
    assert evidence["coupling"]["arena_influences_evolution"] is True
    assert evidence["coupling"]["real_exploit_traffic"] is False
    assert evidence["observation"]["response_sha256"] == "a" * 64
    assert evidence["arena"]["generations"][0]["matches"] == 3
    assert evidence["arena"]["scope_violations"] == []
