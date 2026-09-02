"""SPEAR phase 5B: bounded same-origin path inventory.

The inventory starts from an exact host/base path already authorized by an
EngagementManifest, downloads one bounded HTML root page, extracts same-origin
links, and verifies a small subset with HEAD. Query strings, fragments,
cross-host links, state-changing-looking paths, credentials, and exploit
payloads are excluded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable

from .authorized_assessment import EngagementError, EngagementManifest, EngagementTarget

MAX_BODY_BYTES = 128 * 1024
SKIP_TOKENS = (
    "/logout", "/log-out", "/signout", "/sign-out", "/delete", "/remove",
    "/destroy", "/unsubscribe", "/terminate", "/revoke", "/reset-password",
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "link"}:
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


@dataclass(frozen=True)
class InventoryReceipt:
    method: str
    path: str
    status: int
    response_bytes: int
    response_sha256: str
    elapsed_ms: float


@dataclass
class InventoryReport:
    schema: str
    engagement_id: str
    authorization_reference: str
    manifest_sha256: str
    target_host: str
    target_url: str
    observed_at_utc: str
    discovered_paths: list[str]
    receipts: list[InventoryReceipt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "receipts": [asdict(item) for item in self.receipts],
            "boundaries": {
                "exact_host_only": True,
                "same_base_path_only": True,
                "query_strings_followed": False,
                "state_changing_paths_skipped": True,
                "methods": ["GET", "HEAD"],
                "credential_guessing": False,
                "exploit_delivery": False,
            },
        }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _target(manifest: EngagementManifest, host: str) -> EngagementTarget:
    normalized = host.strip().rstrip(".").lower()
    for item in manifest.targets:
        if item.host == normalized:
            return item
    raise EngagementError(f"host is not part of engagement: {normalized}")


def _within_base(path: str, base: str) -> bool:
    if base == "/":
        return path.startswith("/")
    root = base.rstrip("/")
    return path == root or path.startswith(root + "/")


def _safe_path(path: str) -> bool:
    lower = path.lower()
    return not any(token in lower for token in SKIP_TOKENS)


def _normalize_candidate(raw: str, root_url: str, target: EngagementTarget) -> str | None:
    if raw.startswith(("mailto:", "javascript:", "data:", "tel:")):
        return None
    absolute = urllib.parse.urljoin(root_url, raw)
    parsed = urllib.parse.urlsplit(absolute)
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if parsed.scheme != target.scheme or host != target.host:
        return None
    path = urllib.parse.unquote(parsed.path or "/")
    if not _within_base(path, target.base_path) or not _safe_path(path):
        return None
    return path


class BoundedPathInventory:
    def __init__(
        self,
        manifest: EngagementManifest,
        target_host: str,
        *,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.manifest = manifest
        self.target = _target(manifest, target_host)
        if opener is None:
            self._open = urllib.request.build_opener(_NoRedirect()).open
        else:
            self._open = opener
        self._sleep = sleeper or time.sleep
        self.timeout_seconds = max(0.5, min(float(timeout_seconds), 10.0))
        self._last_request_at = 0.0
        self._receipts: list[InventoryReceipt] = []

    def _throttle(self) -> None:
        gap = 1.0 / self.manifest.max_rps
        remaining = gap - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)

    def _request(self, method: str, path: str) -> tuple[InventoryReceipt, bytes]:
        if len(self._receipts) >= self.manifest.max_requests_per_target:
            raise EngagementError("engagement request budget exhausted")
        if not _within_base(path, self.target.base_path) or not _safe_path(path):
            raise EngagementError(f"path is outside bounded inventory scope: {path}")
        url = self.target.url(path)
        self._throttle()
        request = urllib.request.Request(
            url,
            method=method,
            headers={"User-Agent": "Senju-SPEAR-Inventory/1.0", "Accept": "text/html,*/*;q=0.5"},
        )
        started = time.monotonic()
        body = b""
        status = 0
        try:
            response = self._open(request, timeout=self.timeout_seconds)
            status = int(response.status)
            if method == "GET":
                body = response.read(MAX_BODY_BYTES + 1)
            try:
                response.close()
            except Exception:
                pass
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            if method == "GET":
                body = exc.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise EngagementError("inventory response exceeded bounded body limit")
        self._last_request_at = time.monotonic()
        receipt = InventoryReceipt(
            method=method,
            path=path,
            status=status,
            response_bytes=len(body),
            response_sha256=hashlib.sha256(body).hexdigest(),
            elapsed_ms=round((time.monotonic() - started) * 1000.0, 2),
        )
        self._receipts.append(receipt)
        return receipt, body

    def run(self, *, now: dt.datetime | None = None) -> InventoryReport:
        current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        self.manifest.validate(now=current, enforce_window=True)
        self.target.validate(allow_http=self.manifest.allow_http)
        root_path = self.target.base_path
        _, body = self._request("GET", root_path)

        parser = _LinkParser()
        try:
            parser.feed(body.decode("utf-8", errors="ignore"))
        except Exception:
            pass
        root_url = self.target.url(root_path)
        candidates = sorted({
            path
            for raw in parser.hrefs
            if (path := _normalize_candidate(raw, root_url, self.target)) is not None
            and path != root_path
        })

        remaining = max(0, self.manifest.max_requests_per_target - len(self._receipts))
        selected = candidates[:remaining]
        for path in selected:
            self._request("HEAD", path)

        return InventoryReport(
            schema="senju-spear-path-inventory/v1",
            engagement_id=self.manifest.engagement_id,
            authorization_reference=self.manifest.authorization_reference,
            manifest_sha256=self.manifest.sha256(),
            target_host=self.target.host,
            target_url=root_url,
            observed_at_utc=current.isoformat(timespec="seconds"),
            discovered_paths=[root_path, *selected],
            receipts=list(self._receipts),
        )


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run bounded authorized SPEAR path inventory")
    p.add_argument("manifest")
    p.add_argument("--target-host", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args(list(argv) if argv is not None else None)
    manifest = EngagementManifest.load(args.manifest)
    report = BoundedPathInventory(manifest, args.target_host, timeout_seconds=args.timeout).run()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
