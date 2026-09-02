from __future__ import annotations

import datetime as dt
import io

from senju.authorized_assessment import EngagementManifest
from senju.spear_inventory import BoundedPathInventory


class _Headers(dict):
    pass


class _Response:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = io.BytesIO(body)
        self.headers = _Headers()

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)

    def close(self) -> None:
        pass


def manifest() -> EngagementManifest:
    now = dt.datetime.now(dt.timezone.utc)
    return EngagementManifest.from_dict({
        "engagement_id": "inventory-test",
        "owner": "owner",
        "authorization_reference": "ticket-2",
        "valid_from_utc": (now - dt.timedelta(minutes=1)).isoformat(),
        "valid_until_utc": (now + dt.timedelta(hours=1)).isoformat(),
        "targets": [{"host": "owned.example", "scheme": "https", "base_path": "/app/"}],
        "max_requests_per_target": 4,
        "max_rps": 2.0,
        "destructive": False,
    })


def fake_open(request, timeout: float):  # noqa: ANN001
    if request.method == "GET":
        body = b'''<html><body>
        <a href="/app/dashboard">dashboard</a>
        <a href="/app/docs?x=1">docs</a>
        <a href="/app/logout">logout</a>
        <a href="https://other.example/app/out">other</a>
        <a href="/outside">outside</a>
        </body></html>'''
        return _Response(200, body)
    return _Response(200)


def test_inventory_stays_same_host_base_path_and_skips_stateful_paths() -> None:
    report = BoundedPathInventory(manifest(), "owned.example", opener=fake_open, sleeper=lambda _: None).run()
    data = report.to_dict()
    assert data["schema"] == "senju-spear-path-inventory/v1"
    assert data["discovered_paths"] == ["/app/", "/app/dashboard", "/app/docs"]
    assert all(item["method"] in {"GET", "HEAD"} for item in data["receipts"])
    assert data["boundaries"]["query_strings_followed"] is False
    assert data["boundaries"]["state_changing_paths_skipped"] is True


def test_inventory_obeys_request_budget() -> None:
    m = manifest()
    report = BoundedPathInventory(m, "owned.example", opener=fake_open, sleeper=lambda _: None).run()
    assert len(report.receipts) <= m.max_requests_per_target
