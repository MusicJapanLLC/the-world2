from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import engine.discovery_probe_runner as runner


def _write_queue(state: Path, actions: list[dict]) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / "discovery_action_queue.json").write_text(
        json.dumps({"actions": actions}), encoding="utf-8"
    )


def test_probe_runner_executes_ready_scan_probe_without_credentials(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "meta_state"
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact(self, url: str, *, method: str = "GET"):
            calls.append((url, method))
            return SimpleNamespace(
                status=204,
                final_url=url,
                resolved_ips=("203.0.113.10",),
            )

    monkeypatch.setattr(runner, "ExternalContactClient", FakeClient)
    _write_queue(
        state,
        [
            {
                "target": "owner.example",
                "url": "https://owner.example/health",
                "status": "ready",
                "capabilities": ["scan", "probe", "credentialed_action"],
                "credential_scope": "owner-api-service",
                "authorization_reference": "root:owner.example",
            }
        ],
    )

    result = runner.run_discovery_probe_cycle(state)

    assert result["attempted"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert calls == [("https://owner.example/health", "HEAD")]
    assert result["receipts"][0]["credential_scope"] == "none"
    assert (state / "shared_probe_receipts.json").exists()


def test_probe_runner_ignores_non_probe_actions_and_respects_limit(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "meta_state"
    calls: list[str] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact(self, url: str, *, method: str = "GET"):
            calls.append(url)
            return SimpleNamespace(status=200, final_url=url, resolved_ips=("203.0.113.11",))

    monkeypatch.setattr(runner, "ExternalContactClient", FakeClient)
    _write_queue(
        state,
        [
            {
                "target": "write.owner.example",
                "url": "https://write.owner.example/",
                "status": "ready",
                "capabilities": ["write", "mutation"],
                "credential_scope": "none",
            },
            {
                "target": "a.owner.example",
                "url": "https://a.owner.example/",
                "status": "ready",
                "capabilities": ["probe"],
                "credential_scope": "none",
            },
            {
                "target": "b.owner.example",
                "url": "https://b.owner.example/",
                "status": "ready",
                "capabilities": ["scan"],
                "credential_scope": "none",
            },
        ],
    )

    result = runner.run_discovery_probe_cycle(state, max_targets=1)

    assert result["attempted"] == 1
    assert calls == ["https://a.owner.example/"]
