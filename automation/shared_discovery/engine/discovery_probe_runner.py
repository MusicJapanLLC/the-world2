"""Execute real read-only probes for shared discovery targets already authorized.

The runner consumes discovery_action_queue.json. Only scan/probe capabilities are
executed automatically here; write, mutation, and credentialed actions remain separate
explicit action profiles and are never invented from discovery.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

# Reuse Senju's production external contact boundary without requiring callers to
# customize PYTHONPATH when this module runs from automation/codegen.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

PROBE_RECEIPT_SCHEMA = "meta-discovery-probe-receipts/v1"


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def run_discovery_probe_cycle(
    state_dir: str | Path,
    *,
    max_targets: int = 20,
) -> dict[str, Any]:
    state = Path(state_dir)
    queue = _load_json(state / "discovery_action_queue.json", {})
    rows = queue.get("actions", []) if isinstance(queue, dict) else []
    if not isinstance(rows, list):
        rows = []

    receipts: list[dict[str, Any]] = []
    attempted = 0
    succeeded = 0
    failed = 0
    limit = max(1, min(int(max_targets), 50))

    for row in rows:
        if attempted >= limit:
            break
        if not isinstance(row, dict) or row.get("status") != "ready":
            continue
        capabilities = {str(item).strip().lower() for item in row.get("capabilities", [])}
        if not capabilities.intersection({"scan", "probe"}):
            continue
        host = str(row.get("target", "")).strip().lower()
        url = str(row.get("url", "")).strip()
        if not host or not url:
            continue

        attempted += 1
        started = time.monotonic()
        policy = ExternalContactPolicy.from_hosts(
            [host],
            allow_http=False,
            allow_delete=False,
            follow_redirects=False,
            timeout_seconds=5.0,
            max_response_bytes=64 * 1024,
            retries=0,
        )
        client = ExternalContactClient(policy)
        try:
            receipt = client.contact(url, method="HEAD")
            succeeded += 1
            receipts.append(
                {
                    "host": host,
                    "url": url,
                    "status": "success",
                    "http_status": receipt.status,
                    "final_url": receipt.final_url,
                    "resolved_ips": list(receipt.resolved_ips),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "authorization_reference": row.get("authorization_reference"),
                    "capability": "probe",
                    "credential_scope": "none",
                }
            )
        except (ExternalContactError, OSError, TimeoutError) as exc:
            failed += 1
            receipts.append(
                {
                    "host": host,
                    "url": url,
                    "status": "failed",
                    "error": str(exc)[:300],
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "authorization_reference": row.get("authorization_reference"),
                    "capability": "probe",
                    "credential_scope": "none",
                }
            )

    payload = {
        "schema": PROBE_RECEIPT_SCHEMA,
        "generated_at": int(time.time()),
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "receipts": receipts,
    }
    state.mkdir(parents=True, exist_ok=True)
    # Name intentionally avoids discovery/crawler/log tokens so the shared discovery
    # source scanner cannot ingest its own execution receipts on the next cycle.
    (state / "shared_probe_receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload
