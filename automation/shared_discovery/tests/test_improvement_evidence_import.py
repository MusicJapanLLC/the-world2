from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from engine.improvement_evidence_import import (
    EvidenceImportError,
    import_allowed_evidence_zip,
)


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_importer_only_materializes_allowlisted_secret_free_evidence(tmp_path: Path) -> None:
    payload = _zip(
        {
            ".the-world-runtime/the_world_unified_loop.json": json.dumps({"closed_loop": True}).encode(),
            ".the-world-runtime/the_world_final_contract.json": json.dumps({"complete": True}).encode(),
            ".the-world-runtime/credential_runtime/lease.json": json.dumps({"credential_ref": "opaque"}).encode(),
            ".the-world-runtime/random.txt": b"ignore me",
        }
    )
    result = import_allowed_evidence_zip(tmp_path, payload)

    assert result["imported_count"] == 2
    assert (tmp_path / "the_world_unified_loop.json").exists()
    assert (tmp_path / "the_world_final_contract.json").exists()
    assert not (tmp_path / "lease.json").exists()
    assert not (tmp_path / "random.txt").exists()
    assert result["authority_imported"] is False
    assert result["credentials_imported"] is False
    assert result["raw_secrets_imported"] is False


def test_invalid_json_evidence_fails_closed(tmp_path: Path) -> None:
    payload = _zip({"the_world_final_contract.json": b"{bad json"})
    with pytest.raises(EvidenceImportError, match="invalid JSON"):
        import_allowed_evidence_zip(tmp_path, payload)
