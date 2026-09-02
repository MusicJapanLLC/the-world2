from __future__ import annotations

import json
from pathlib import Path

import pytest

from senju.federation import FederationError, compile_steps, run_federation


class FakeReceipt:
    def __init__(self, url: str, status: int, body: bytes, method: str):
        import hashlib
        self.url = url
        self._data = {
            "schema": "senju-external-contact/v3",
            "contacted_at_utc": "2026-08-30T00:00:00+00:00",
            "method": method,
            "requested_url": url,
            "final_url": url,
            "host": "api.example.test",
            "final_host": "api.example.test",
            "contacted_hosts": ["api.example.test"],
            "resolved_ips": ["203.0.113.7"],
            "status": status,
            "provider_acknowledged": 200 <= status < 400,
            "response_bytes": len(body),
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "content_type": "application/json",
            "etag": None,
            "last_modified": None,
            "retry_after": None,
            "attempt_count": 1,
            "redirect_count": 0,
            "url": url,
        }

    def to_dict(self):
        return dict(self._data)

    def write(self, path):
        Path(path).write_text(json.dumps(self._data), encoding="utf-8")


class FakeResult:
    def __init__(self, url, method, status, payload):
        self.body = json.dumps(payload).encode()
        self.receipt = FakeReceipt(url, status, self.body, method)

    def write_body(self, path):
        Path(path).write_bytes(self.body)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def contact_with_body(self, url, *, method="GET", body=None, headers=None):
        self.calls.append(
            {
                "url": url,
                "method": method,
                "body": body,
                "headers": dict(headers or {}),
            }
        )
        status, payload = self.responses.pop(0)
        return FakeResult(url, method, status, payload)


def doc(producer, steps, priority=50):
    return {
        "schema": "senju-action-intents/v1",
        "producer": producer,
        "priority": priority,
        "steps": steps,
    }


def test_cross_producer_dependency_and_response_chaining(tmp_path):
    client = FakeClient(
        [
            (200, {"url": "https://api.example.test/repos/acme/core"}),
            (200, {"sha": "abc123"}),
            (200, {"workflow_count": 4}),
        ]
    )
    docs = [
        doc(
            "BOSS",
            [{"id": "repo", "url": "https://api.example.test/repos/acme/core"}],
        ),
        doc(
            "RND",
            [
                {
                    "id": "commit",
                    "after": ["repo"],
                    "url": "{{steps.repo.json.url}}/commits/latest",
                }
            ],
        ),
        doc(
            "FOUNDRY",
            [
                {
                    "id": "workflow",
                    "after": ["commit"],
                    "url": "{{steps.repo.json.url}}/actions/workflows",
                }
            ],
        ),
    ]

    report = run_federation(
        docs,
        allow_hosts=["api.example.test"],
        client=client,
        out_dir=tmp_path,
        run_id="test-run",
    )

    assert report["success"] is True
    assert [x["id"] for x in report["steps"]] == ["repo", "commit", "workflow"]
    assert client.calls[1]["url"].endswith("/commits/latest")
    assert client.calls[2]["url"].endswith("/actions/workflows")
    assert report["producers"] == ["BOSS", "FOUNDRY", "RND"]


def test_priority_never_breaks_dependency_order():
    plan = compile_steps(
        [
            doc(
                "BOSS",
                [
                    {"id": "a", "url": "https://api.example.test/a", "priority": 1},
                    {
                        "id": "b",
                        "after": ["a"],
                        "url": "https://api.example.test/b",
                        "priority": 999,
                    },
                    {"id": "c", "url": "https://api.example.test/c", "priority": 50},
                ],
            )
        ]
    )
    assert [x.id for x in plan] == ["c", "a", "b"]


def test_dependency_cycle_is_rejected():
    with pytest.raises(FederationError, match="cycle"):
        compile_steps(
            [
                doc(
                    "RND",
                    [
                        {"id": "a", "after": ["b"], "url": "https://api.example.test/a"},
                        {"id": "b", "after": ["a"], "url": "https://api.example.test/b"},
                    ],
                )
            ]
        )


def test_write_requires_executor_max_effect(tmp_path):
    client = FakeClient([(201, {"id": 1})])
    docs = [doc("FOUNDRY", [{"id": "create", "method": "POST", "url": "https://api.example.test/jobs"}])]
    with pytest.raises(FederationError, match="exceeds executor"):
        run_federation(
            docs,
            allow_hosts=["api.example.test"],
            max_effect="read",
            client=client,
            out_dir=tmp_path,
        )


def test_delete_requires_two_explicit_opt_ins(tmp_path):
    docs = [doc("BOSS", [{"id": "remove", "method": "DELETE", "url": "https://api.example.test/jobs/1"}])]
    client = FakeClient([(204, {})])
    with pytest.raises(FederationError, match="requires both"):
        run_federation(
            docs,
            allow_hosts=["api.example.test"],
            max_effect="delete",
            allow_delete=False,
            client=client,
            out_dir=tmp_path,
        )

    client = FakeClient([(204, {})])
    report = run_federation(
        docs,
        allow_hosts=["api.example.test"],
        max_effect="delete",
        allow_delete=True,
        client=client,
        out_dir=tmp_path,
    )
    assert report["success"] is True
    assert client.calls[0]["method"] == "DELETE"


def test_secret_header_requires_executor_allowlist_and_is_not_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "super-secret-value")
    docs = [
        doc(
            "RND",
            [
                {
                    "id": "auth",
                    "url": "https://api.example.test/private",
                    "headers": {
                        "Authorization": {
                            "secret_env": "API_TOKEN",
                            "prefix": "Bearer ",
                        }
                    },
                }
            ],
        )
    ]
    client = FakeClient([(200, {"ok": True})])

    with pytest.raises(FederationError, match="not executor-allowed"):
        run_federation(
            docs,
            allow_hosts=["api.example.test"],
            client=client,
            out_dir=tmp_path,
        )

    client = FakeClient([(200, {"ok": True})])
    report = run_federation(
        docs,
        allow_hosts=["api.example.test"],
        allowed_secret_env=["API_TOKEN"],
        client=client,
        out_dir=tmp_path,
    )
    assert client.calls[0]["headers"]["Authorization"] == "Bearer super-secret-value"
    assert "super-secret-value" not in json.dumps(report)
    assert "super-secret-value" not in (tmp_path / "federation-run.json").read_text()


def test_json_body_can_use_prior_response_and_run_id(tmp_path):
    client = FakeClient([(200, {"id": 42}), (201, {"saved": True})])
    docs = [
        doc(
            "RND",
            [{"id": "discover", "url": "https://api.example.test/discover"}],
        ),
        doc(
            "FOUNDRY",
            [
                {
                    "id": "store",
                    "after": ["discover"],
                    "method": "POST",
                    "url": "https://api.example.test/jobs",
                    "json": {
                        "discovered_id": "{{steps.discover.json.id}}",
                        "run_id": "{{run.id}}",
                    },
                    "expect_status": 201,
                }
            ],
        ),
    ]
    report = run_federation(
        docs,
        allow_hosts=["api.example.test"],
        max_effect="write",
        client=client,
        out_dir=tmp_path,
        run_id="fed-123",
    )
    sent = json.loads(client.calls[1]["body"])
    assert sent == {"discovered_id": 42, "run_id": "fed-123"}
    assert report["success"] is True


def test_unexpected_status_stops_by_default(tmp_path):
    client = FakeClient([(500, {"error": "nope"}), (200, {"never": True})])
    docs = [
        doc(
            "BOSS",
            [
                {"id": "first", "url": "https://api.example.test/fail"},
                {
                    "id": "second",
                    "after": ["first"],
                    "url": "https://api.example.test/next",
                },
            ],
        )
    ]
    report = run_federation(
        docs,
        allow_hosts=["api.example.test"],
        client=client,
        out_dir=tmp_path,
    )
    assert report["success"] is False
    assert report["executed_steps"] == 1
    assert len(client.calls) == 1
