from __future__ import annotations

import datetime as dt
import hashlib
import urllib.parse

from senju.external import ContactReceipt, ContactResult
from senju.owned_range_active import MEMORY_SCHEMA, OwnedRangeActiveRunner, OwnedRangeMemory
from senju.trusted_scope import TrustedOwnerScope

BASE = "https://kabeya-authorized-test-range.onrender.com/"
HOST = "kabeya-authorized-test-range.onrender.com"


def _scope() -> TrustedOwnerScope:
    return TrustedOwnerScope.from_dict(
        {
            "scope_id": "kabeya-authorized-test-range",
            "owner": "Owner/BOSS",
            "domain_roots": [HOST],
            "effect_level": "state_change",
            "allowed_methods": ["GET", "HEAD", "OPTIONS", "POST"],
            "max_rps": 5,
            "recursive_same_origin": True,
        }
    )


class FakeClient:
    def __init__(self, *, password_form: bool = False) -> None:
        self.password_form = password_form
        self.last_marker = ""
        self.calls: list[tuple[str, str]] = []

    def _receipt(self, url: str, method: str, body: bytes, *, status: int = 200, content_type: str = "text/html") -> ContactReceipt:
        return ContactReceipt(
            schema="senju-external-contact/v3",
            contacted_at_utc="2026-08-31T04:00:00+00:00",
            method=method,
            requested_url=url,
            final_url=url,
            host=HOST,
            final_host=HOST,
            contacted_hosts=(HOST,),
            resolved_ips=("203.0.113.10",),
            status=status,
            provider_acknowledged=200 <= status < 400,
            response_bytes=len(body),
            response_sha256=hashlib.sha256(body).hexdigest(),
            content_type=content_type,
            etag=None,
            last_modified=None,
            retry_after=None,
            attempt_count=1,
            redirect_count=0,
        )

    def contact_with_body(self, url: str, *, method: str = "GET", body=None, headers=None):  # noqa: ANN001, ANN003
        self.calls.append((method, url))
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        if method == "POST":
            decoded = (body or b"").decode("utf-8", errors="ignore")
            params = urllib.parse.parse_qs(decoded)
            joined = " ".join(v for values in params.values() for v in values)
            for token in joined.split():
                if token.startswith("SENJU_"):
                    self.last_marker = token.strip()
                    break
            response = b"accepted"
            return ContactResult(self._receipt(url, method, response), response)

        if method in {"HEAD", "OPTIONS"}:
            response = b""
            return ContactResult(self._receipt(url, method, response), response)

        if parsed.path in {"/scope.json", "/robots.txt", "/.well-known/security.txt"}:
            response = b"{}" if parsed.path.endswith(".json") else b"ok"
            ctype = "application/json" if parsed.path.endswith(".json") else "text/plain"
            return ContactResult(self._receipt(url, method, response, content_type=ctype), response)

        if "senju_probe" in query:
            value = query["senju_probe"][-1]
            response = f"probe={value}".encode()
            return ContactResult(self._receipt(url, method, response), response)

        role = (query.get("role") or query.get("Role") or [""])[-1]
        if role in {"admin", "staff", "owner"}:
            response = ("internal admin dashboard " * 12).encode()
            return ContactResult(self._receipt(url, method, response), response)
        if role in {"user", "guest", "viewer"}:
            response = b"public view"
            return ContactResult(self._receipt(url, method, response), response)

        if self.password_form:
            html = """
            <html><body>
              <form action="/login" method="post">
                <input name="username">
                <input name="password" type="password">
              </form>
            </body></html>
            """
        else:
            marker = f"<div>{self.last_marker}</div>" if self.last_marker else ""
            html = f"""
            <html><body>
              <a href="/about">About</a>
              <a href="/contact">Contact</a>
              <a href="https://third-party.example/out">External</a>
              <form action="/api/contact" method="post">
                <input name="name">
                <input name="email" type="email">
                <textarea name="message"></textarea>
              </form>
              {marker}
            </body></html>
            """
        response = html.encode()
        return ContactResult(self._receipt(url, method, response), response)


def test_active_loop_discovers_same_origin_probes_controls_and_reads_back_write() -> None:
    fake = FakeClient()
    runner = OwnedRangeActiveRunner(_scope(), base_url=BASE, client=fake, sleeper=lambda _: None)
    report, memory = runner.run(
        max_pages=6,
        max_probe_requests=16,
        max_writes=2,
        write_cooldown_seconds=3600,
        seed=7,
        now=dt.datetime(2026, 8, 31, 4, 0, tzinfo=dt.timezone.utc),
    )

    assert report["same_origin_only"] is True
    assert report["authority_self_expansion"] is False
    assert report["destructive_requests"] is False
    assert any("third-party.example" in url for url in report["external_links_skipped"])
    assert all(HOST in url for method, url in fake.calls if url.startswith("https://") and "third-party.example" not in url)
    assert report["write_attempts"] == 1
    assert report["write_provider_acks"] == 1
    assert report["independent_readbacks"] == 1
    assert any(row["probe"] == "role_diff" for row in report["counterexamples"])
    assert memory["schema"] == MEMORY_SCHEMA


def test_sensitive_password_form_is_never_submitted() -> None:
    fake = FakeClient(password_form=True)
    runner = OwnedRangeActiveRunner(_scope(), base_url=BASE, client=fake, sleeper=lambda _: None)
    report, _ = runner.run(
        max_pages=1,
        max_probe_requests=2,
        max_writes=3,
        seed=3,
        now=dt.datetime(2026, 8, 31, 4, 0, tzinfo=dt.timezone.utc),
    )
    assert report["write_attempts"] == 0
    assert not any(method == "POST" for method, _ in fake.calls)


def test_write_cooldown_prevents_quarter_hour_form_spam() -> None:
    first_client = FakeClient()
    first_runner = OwnedRangeActiveRunner(_scope(), base_url=BASE, client=first_client, sleeper=lambda _: None)
    first, memory = first_runner.run(
        max_pages=2,
        max_probe_requests=2,
        max_writes=1,
        write_cooldown_seconds=3600,
        now=dt.datetime(2026, 8, 31, 4, 0, tzinfo=dt.timezone.utc),
    )
    assert first["write_attempts"] == 1

    second_client = FakeClient()
    second_runner = OwnedRangeActiveRunner(_scope(), base_url=BASE, client=second_client, sleeper=lambda _: None)
    second, _ = second_runner.run(
        memory_data=memory,
        max_pages=2,
        max_probe_requests=2,
        max_writes=1,
        write_cooldown_seconds=3600,
        now=dt.datetime(2026, 8, 31, 4, 15, tzinfo=dt.timezone.utc),
    )
    assert second["write_attempts"] == 0
    assert not any(method == "POST" for method, _ in second_client.calls)


def test_productive_probe_family_rises_in_next_ranking() -> None:
    memory = OwnedRangeMemory()
    for _ in range(5):
        memory.record_probe("role_diff", interesting=True, failed=False, reason="privilege_hint_diff:admin")
    for family in ("debug_diff", "id_diff", "mode_diff"):
        for _ in range(5):
            memory.record_probe(family, interesting=False, failed=False, reason="no_material_diff")
    ranking = sorted(
        ("role_diff", "debug_diff", "id_diff", "mode_diff"),
        key=lambda family: (-memory.family_score(family), family),
    )
    assert ranking[0] == "role_diff"
