import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.discovery_authorization import run_discovery_authorization


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_promotes_only_trusted_root_and_subdomain(tmp_path: Path):
    _write(
        tmp_path / "discovery_policy.json",
        {"trusted_roots": ["owned.example.com"]},
    )
    _write(
        tmp_path / "discovered_urls.json",
        {
            "links": [
                "https://owned.example.com/a",
                "https://api.owned.example.com/b",
                "https://third-party.example.net/c",
            ]
        },
    )

    result = run_discovery_authorization(tmp_path, ttl_seconds=600)

    assert result["authorized_hosts"] == [
        "api.owned.example.com",
        "owned.example.com",
    ]
    authorized = json.loads((tmp_path / "discovery_authorized.json").read_text())
    assert authorized["hosts"]["owned.example.com"]["allowed_methods"] == ["GET", "HEAD"]
    assert "third-party.example.net" not in authorized["hosts"]

    candidates = json.loads((tmp_path / "discovery_candidates.json").read_text())
    third_party = [
        item for item in candidates["candidates"]
        if item["host"] == "third-party.example.net"
    ][0]
    assert third_party["decision"] == "candidate_only"


def test_explicit_host_field_is_a_candidate(tmp_path: Path):
    _write(tmp_path / "discovery_policy.json", {"trusted_roots": ["owned.example.com"]})
    _write(
        tmp_path / "discovered_urls.json",
        {"hostname": "worker.owned.example.com"},
    )

    result = run_discovery_authorization(tmp_path)
    assert result["authorized_hosts"] == ["worker.owned.example.com"]


def test_http_credentials_and_ip_literals_do_not_promote(tmp_path: Path):
    _write(tmp_path / "discovery_policy.json", {"trusted_roots": ["owned.example.com"]})
    _write(
        tmp_path / "discovered_urls.json",
        {
            "links": [
                "http://owned.example.com/plain",
                "https://user:pass@owned.example.com/secret",
            ],
            "host": "127.0.0.1",
        },
    )

    result = run_discovery_authorization(tmp_path)
    assert result["authorized_count"] == 0
