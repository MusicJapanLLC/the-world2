#!/usr/bin/env python3
"""Continuous adversarial exercise for the explicitly authorized synthetic range.

The target host is intentionally fixed. This runner does not accept arbitrary targets.
It performs normal-rate crawling, query mutation, known weak-surface checks, client-side
credential exposure checks, and non-destructive synthetic write-method probes.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://kabeya-authorized-test-range.onrender.com"
AUTHORIZED_HOST = "kabeya-authorized-test-range.onrender.com"
MAX_RPS = 10.0
TIMEOUT = 15

READ_PATHS = [
    "/",
    "/scope.json",
    "/ai.txt",
    "/.well-known/security.txt",
    "/lab/index.html",
    "/lab/nullharbor.html?role=admin&debug=1",
    "/lab/embermesh.html?id=0",
    "/lab/embermesh.html?id=1",
    "/lab/atlaspaper.html",
    "/lab/lumenclause.html?q=%27%22%3C%3E%26",
    "/lab/orbitnotes.html",
    "/lab/archive-demo.txt",
    "/login-lab/",
    "/login-lab/app.js",
    "/login-lab/data.json",
]

WRITE_PROBES = [
    ("POST", "/contact/index.html", b"name=senju-test&message=synthetic-only"),
    ("PUT", "/login-lab/synthetic-records/senju-probe", b'{"synthetic":true,"source":"senju"}'),
    ("PATCH", "/login-lab/synthetic-records/senju-probe", b'{"synthetic":true,"note":"mutation-probe"}'),
    ("DELETE", "/login-lab/synthetic-records/senju-probe", None),
]


def assert_authorized(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != AUTHORIZED_HOST:
        raise RuntimeError(f"refusing out-of-scope URL: {url}")


def request(method: str, path: str, body: bytes | None = None) -> dict:
    url = urllib.parse.urljoin(BASE + "/", path.lstrip("/"))
    assert_authorized(url)
    headers = {
        "User-Agent": "Senju-Authorized-Range-Exercise/1.0",
        "X-Senju-Test": "synthetic-authorized-range",
    }
    if body is not None:
        headers["Content-Type"] = "application/json" if body.startswith(b"{") else "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            data = res.read(1024 * 1024)
            status = res.status
            final_url = res.geturl()
    except urllib.error.HTTPError as exc:
        data = exc.read(1024 * 1024)
        status = exc.code
        final_url = exc.geturl()
    elapsed_ms = round((time.time() - started) * 1000, 1)
    assert_authorized(final_url)
    text = data.decode("utf-8", errors="replace")
    return {
        "method": method,
        "url": url,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "signals": {
            "flag_marker": "FLAG{" in text,
            "demo_email_exposed": "redteam@example.test" in text,
            "demo_password_exposed": "lab-pass-314" in text,
            "static_token_exposed": "DEMO_ATLAS_0000_NOT_A_SECRET" in text,
            "authorization_policy_present": "AUTHORIZED" in text.upper(),
        },
    }


def main() -> int:
    interval = 1.0 / MAX_RPS
    observations: list[dict] = []
    for path in READ_PATHS:
        observations.append(request("GET", path))
        time.sleep(interval)
    for method, path, body in WRITE_PROBES:
        observations.append(request(method, path, body))
        time.sleep(interval)

    report = {
        "schema": "senju-authorized-range-assault/v1",
        "target": BASE,
        "authorization": "fixed-owner-authorized-synthetic-range",
        "request_count": len(observations),
        "observations": observations,
        "summary": {
            "flag_surfaces": sum(1 for x in observations if x["signals"]["flag_marker"]),
            "demo_credentials_exposed": any(
                x["signals"]["demo_email_exposed"] or x["signals"]["demo_password_exposed"] for x in observations
            ),
            "static_token_exposed": any(x["signals"]["static_token_exposed"] for x in observations),
            "write_methods_accepted_2xx": [
                x["method"] for x in observations if x["method"] in {"POST", "PUT", "PATCH", "DELETE"} and 200 <= x["status"] < 300
            ],
        },
    }
    out = Path("authorized-range-assault-report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
