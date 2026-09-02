"""Import sanitized The World runtime evidence from a successful same-repo workflow.

The importer is intentionally narrow: it only reads GitHub Actions artifacts from the
current MusicJapanLLC/test repository and only materializes an allowlist of JSON/NDJSON
evidence files that are already designed to be secret-free. It never imports caches,
credential-runtime state, raw environment data, arbitrary artifact paths, or authority
configuration as authority.
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Mapping

PRODUCTION_REPOSITORY = "MusicJapanLLC/test"
WORKFLOW_FILE = "the-world-unified-loop.yml"
ARTIFACT_PREFIX = "the-world-unified-loop-"
ALLOWED_EVIDENCE_BASENAMES = frozenset(
    {
        "the_world_unified_loop.json",
        "the_world_final_contract.json",
        "discovery_action_failover_run.json",
        "discovery_external_action_receipts.json",
        "external_action_denials.ndjson",
        "discovery_capability_leases.json",
        "the_world_persistent_queue.json",
        "authority_opportunity_queue.json",
    }
)


class EvidenceImportError(RuntimeError):
    """Raised when bounded production evidence import cannot be completed."""


class _StripSensitiveCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow GitHub artifact redirects without leaking GitHub authorization headers."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlsplit(req.full_url).hostname
        new_host = urllib.parse.urlsplit(newurl).hostname
        if old_host != new_host:
            for header in ("Authorization", "X-GitHub-Api-Version"):
                redirected.remove_header(header)
                redirected.headers.pop(header, None)
                redirected.unredirected_hdrs.pop(header, None)
        return redirected


def _default_open(request: urllib.request.Request, *, timeout: int) -> Any:
    opener = urllib.request.build_opener(_StripSensitiveCrossHostRedirect())
    return opener.open(request, timeout=timeout)


def _request_bytes(url: str, token: str, *, opener: Callable[..., Any] | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "The-World-Authority-Improvement/1.0",
        },
    )
    open_fn = opener or _default_open
    try:
        with open_fn(request, timeout=20) as response:
            data = bytes(response.read(8 * 1024 * 1024 + 1))
            if len(data) > 8 * 1024 * 1024:
                raise EvidenceImportError("GitHub evidence response exceeded size limit")
            return data
    except EvidenceImportError:
        raise
    except (OSError, TimeoutError, urllib.error.HTTPError) as exc:
        raise EvidenceImportError(f"GitHub evidence request failed: {type(exc).__name__}") from exc


def _request_json(url: str, token: str, *, opener: Callable[..., Any] | None = None) -> Mapping[str, Any]:
    raw = _request_bytes(url, token, opener=opener)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceImportError("GitHub evidence response is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise EvidenceImportError("GitHub evidence response must be an object")
    return value


def import_allowed_evidence_zip(destination: str | Path, payload: bytes) -> dict[str, Any]:
    """Extract only explicitly allowlisted secret-free evidence basenames."""
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, Any]] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise EvidenceImportError("workflow artifact is not a valid ZIP") from exc

    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            basename = Path(info.filename).name
            if basename not in ALLOWED_EVIDENCE_BASENAMES:
                continue
            if info.file_size > 4 * 1024 * 1024:
                raise EvidenceImportError(f"evidence file too large: {basename}")
            data = archive.read(info)
            # Every imported record is textual JSON/NDJSON evidence. Validate UTF-8 and
            # basic parseability before it can influence the improvement bus.
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EvidenceImportError(f"evidence is not UTF-8: {basename}") from exc
            if basename.endswith(".json"):
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    raise EvidenceImportError(f"invalid JSON evidence: {basename}") from exc
            else:
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise EvidenceImportError(f"invalid NDJSON evidence: {basename}") from exc
            target = dest / basename
            target.write_text(text, encoding="utf-8")
            imported.append({"name": basename, "source_path": info.filename, "bytes": len(data)})

    return {
        "imported_count": len(imported),
        "imported": imported,
        "authority_imported": False,
        "credentials_imported": False,
        "raw_secrets_imported": False,
    }


def import_latest_world_evidence(
    destination: str | Path,
    *,
    token: str | None = None,
    repository: str | None = None,
    branch: str = "claude/employee-onboarding-setup-udm86",
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download the newest successful World artifact and extract allowlisted evidence."""
    repo = str(repository or os.environ.get("GITHUB_REPOSITORY", "")).strip()
    if repo != PRODUCTION_REPOSITORY:
        raise EvidenceImportError("evidence import is restricted to the production repository")
    auth = str(token or os.environ.get("GITHUB_TOKEN", "")).strip()
    if not auth:
        raise EvidenceImportError("GITHUB_TOKEN is required for workflow evidence import")

    api = f"https://api.github.com/repos/{PRODUCTION_REPOSITORY}"
    runs_url = (
        f"{api}/actions/workflows/{WORKFLOW_FILE}/runs"
        f"?branch={branch}&status=success&per_page=5"
    )
    runs = _request_json(runs_url, auth, opener=opener).get("workflow_runs", [])
    if not isinstance(runs, list) or not runs:
        return {"imported_count": 0, "reason": "no_successful_world_run", "authority_imported": False}

    for run in runs:
        if not isinstance(run, Mapping):
            continue
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        artifacts = _request_json(f"{api}/actions/runs/{run_id}/artifacts", auth, opener=opener).get("artifacts", [])
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                continue
            name = str(artifact.get("name", ""))
            artifact_id = artifact.get("id")
            if not name.startswith(ARTIFACT_PREFIX) or not isinstance(artifact_id, int):
                continue
            payload = _request_bytes(f"{api}/actions/artifacts/{artifact_id}/zip", auth, opener=opener)
            result = import_allowed_evidence_zip(destination, payload)
            return {
                **result,
                "source_run_id": run_id,
                "source_artifact_id": artifact_id,
                "source_artifact_name": name,
                "same_repository_only": True,
                "generated_authority_imported": False,
            }

    return {"imported_count": 0, "reason": "no_matching_world_artifact", "authority_imported": False}
