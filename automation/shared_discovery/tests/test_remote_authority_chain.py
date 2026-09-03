import base64
import hashlib
import json
from pathlib import Path

from engine.remote_authority_chain import run_remote_authority_chain


_RSA_A_N = int(
    "e65f1efbbcd05f303bca1fb07d228ede8268cb9df089ea69c076587458a065e6"
    "299f3ec513b644d1a2b1b9eaac24b970dcfccf130a4cd79d4004ec664112b466"
    "ef0ad1258c1d426dabf0c88ca22158f0a6929ba6eaf9ed09114bf8214fbe8ead"
    "0ef7e8607d7d0125a8a9b336e8c15d8243562397bf44a73d25a4a9a58b6b611"
    "00c31795313392a296530bc710e56ab2057d6dc1dcfe1a70f0b8d7d1659fa315"
    "44bef625f335c93fdc524ad5b4c10dfec42d2cbc396c392c94f40d5374448cce"
    "9ac2336b100e7a4da219e3e15bab59ca20fc93d1c520ddbd67b525ae8274b0070"
    "ae15b37cdd2a7db0061c49b62930d2c52d3d61e742f0efe4ddec528fcbf27aad",
    16,
)
_RSA_A_D = int(
    "81629b3c37e7b00e9f05fe965931b79c31123a8a1236e37951a72636f22fe40b"
    "49052f73f08646509757ca5b8b237523767a66b302edf58b54116fd45e67eafa"
    "84f746501849b6ad720c6216da58706378aa8ed148d7e5d159ed9906dc8ae207"
    "4088ebf2858857c496ddf8d1b6182434ad2d0c00866440a98f22d4452df0b92a"
    "015626675c1bb8b199d82b54ab312718e80e35fc3507c06f9be818bc9f492497"
    "ca665357a17fc8639bb8ae062588b71cce0d1d50a833dca8d694490cfbbbf6e6"
    "9dd2b58dbcd616702d13591822461706b627e6696b1203b52700c40f09814eca"
    "b96473367a4592edc34e73d3ca83cfbdaf96765d46218856e5b869d3eb7eb0f",
    16,
)
_RSA_B_N = int(
    "bb66528c479c8664fab097b539ea8caa30b7dcc713719e74f023fc0073945d2c"
    "e6e04a8d300f93d0f3476a65d394f485800f9c642e77d8781e362e67c1990d6b"
    "1f191f174ddc9fc8bed652cade5117e9aefd241eb33598ae1ae7b062eb4058f3c"
    "0ae7a75f9b137bf342c7ac29122b5c74afde60c7b01b1274ed8247e5310a05ce"
    "a2d1e0092e22e80e2614b167938bfc9391e854d8205ff7f8cc44ba04119c7f17"
    "ced766613992190a56e90ab167481135ace74a5488b2be94d45226e70f0cfa19f"
    "d5ca47b26c3119dacf89b87fef9cd1e809929852b16d22891ca6682dc6962e97"
    "755feadea91caf9d1177910fbcc7f9fb63cd3e7d18de4e92c073245f1efb87",
    16,
)
_RSA_B_D = int(
    "523c7f5a16ecdddf3f51b269715e77d711a505ca08c2d1e60021d26b024d67ac"
    "162ef4184c3071cdfe8c66e90375f8ee02ba1707b18a9f206b259caca47cfd31"
    "f686282a2a5d7872f828065207486fe57908964ab09b0302d844b71759a435c4"
    "d5d7db5e9d31c3447169597fbb800f644308f364a3b024e51a88e84ed535d520"
    "dfb2607d238455f6fc26eadd7239781d1dd2ade0d7bcac55b2b451c9b7aa5b42"
    "b2b58376e80ce236a873befc9dc3453f001dda807187477334bfbb90224ad1d1"
    "89347d9f4add19b2798ed4df2be1763c9fd41131bd29b33825026501f6c3756e"
    "1e9e7099be8b3c3597a439f1d6f08be8ba6ad47693cd986aed7d81a455a8aa49",
    16,
)
_RSA_E = 65537
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _policy(state: Path, *roots: str) -> None:
    _write(state / "discovery_policy.json", {"trusted_roots": list(roots)})


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_int(value: int) -> str:
    return _b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _jwk(n: int) -> dict:
    return {"kty": "RSA", "alg": "RS256", "n": _b64u_int(n), "e": _b64u_int(_RSA_E)}


def _sign(document: dict, *, n: int, d: int) -> dict:
    unsigned = dict(document)
    unsigned.pop("signature", None)
    payload = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    size = (n.bit_length() + 7) // 8
    digest_info = _DIGEST_INFO + hashlib.sha256(payload).digest()
    padding = b"\xff" * (size - len(digest_info) - 3)
    encoded = b"\x00\x01" + padding + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), d, n).to_bytes(size, "big")
    return {
        **unsigned,
        "signature": {"alg": "RS256", "value": _b64u(signature)},
    }


def _trust_anchor(repo: Path, host: str, jwk: dict) -> None:
    _write(
        repo / "senju" / "config" / "remote-authority-trust-anchors.json",
        {
            "schema": "meta-remote-authority-trust-anchors/v1",
            "anchors": {host: jwk},
        },
    )


def test_well_known_declaration_builds_recursive_production_chain_inside_owner_root(tmp_path: Path):
    state = tmp_path / "state"
    _policy(state, "owned.example.com")
    _write(
        state / "remote_authority_declarations.json",
        {
            "declarations": [
                {
                    "source_host": "owned.example.com",
                    "source_kind": "well_known_manifest",
                    "evidence_url": "https://owned.example.com/.well-known/security-test-federation.json",
                    "members": ["b.owned.example.com"],
                },
                {
                    "source_host": "b.owned.example.com",
                    "source_kind": "remote_declaration",
                    "authorized_hosts": ["c.owned.example.com"],
                },
                {
                    "source_host": "c.owned.example.com",
                    "source_kind": "linked_registry",
                    "hosts": ["d.owned.example.com"],
                },
            ]
        },
    )

    result = run_remote_authority_chain(state, repo_root=tmp_path / "repo", ttl_seconds=600)
    assert result["environment"] == "production"
    assert result["fixed_chain_depth_limit"] is None
    assert result["promoted_hosts"] == [
        "b.owned.example.com",
        "c.owned.example.com",
        "d.owned.example.com",
    ]

    chain = json.loads((state / "remote_authority_chain.json").read_text())
    d = chain["promoted"]["d.owned.example.com"]
    assert d["lineage"] == [
        "owned.example.com",
        "b.owned.example.com",
        "c.owned.example.com",
        "d.owned.example.com",
    ]
    assert d["depth"] == 3
    assert d["credential_scope"] == "none"
    assert d["allowed_methods"] == ["GET", "HEAD"]


def test_signed_remote_delegation_builds_cross_domain_recursive_production_chain(tmp_path: Path):
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _policy(state, "a.owner.example")
    _trust_anchor(repo, "a.owner.example", _jwk(_RSA_A_N))

    first = _sign(
        {
            "source_host": "a.owner.example",
            "source_kind": "well_known_manifest",
            "evidence_url": "https://a.owner.example/.well-known/authority.json",
            "authorized_hosts": ["b.partner.example.net"],
            "delegation_keys": {"b.partner.example.net": _jwk(_RSA_B_N)},
        },
        n=_RSA_A_N,
        d=_RSA_A_D,
    )
    second = _sign(
        {
            "source_host": "b.partner.example.net",
            "source_kind": "linked_registry",
            "evidence_url": "https://b.partner.example.net/.well-known/authority.json",
            "authorized_hosts": ["c.vendor.example.org"],
        },
        n=_RSA_B_N,
        d=_RSA_B_D,
    )
    _write(
        state / "remote_authority_declarations.json",
        {"declarations": [second, first]},
    )

    result = run_remote_authority_chain(state, repo_root=repo, ttl_seconds=600)
    assert result["signed_promoted_hosts"] == [
        "b.partner.example.net",
        "c.vendor.example.org",
    ]
    assert result["fixed_chain_depth_limit"] is None

    chain = json.loads((state / "remote_authority_chain.json").read_text())
    c = chain["promoted"]["c.vendor.example.org"]
    assert c["authorization_basis"] == "signed_remote_delegation"
    assert c["authorization_reference"] == "b.partner.example.net"
    assert c["signature_verified"] is True
    assert c["lineage"] == [
        "a.owner.example",
        "b.partner.example.net",
        "c.vendor.example.org",
    ]
    assert c["allowed_methods"] == ["GET", "HEAD"]
    assert c["credential_scope"] == "none"
    assert c["effect"] == "read_only"

    live = json.loads((state / "discovery_authorized.json").read_text())
    assert "b.partner.example.net" in live["hosts"]
    assert "c.vendor.example.org" in live["hosts"]


def test_tampered_signed_remote_declaration_cannot_promote_unrelated_host(tmp_path: Path):
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _policy(state, "a.owner.example")
    _trust_anchor(repo, "a.owner.example", _jwk(_RSA_A_N))

    declaration = _sign(
        {
            "source_host": "a.owner.example",
            "source_kind": "remote_policy",
            "authorized_hosts": ["b.partner.example.net"],
        },
        n=_RSA_A_N,
        d=_RSA_A_D,
    )
    declaration["authorized_hosts"] = ["evil.example.net"]
    _write(state / "remote_authority_declarations.json", {"declarations": [declaration]})

    result = run_remote_authority_chain(state, repo_root=repo)
    assert result["signed_promoted_count"] == 0
    assert "evil.example.net" not in result["promoted_hosts"]


def test_remote_host_cannot_self_mint_unrelated_new_trust_root(tmp_path: Path):
    state = tmp_path / "state"
    _policy(state, "owned.example.com")
    _write(
        state / "remote_authority_declarations.json",
        {
            "declarations": [
                {
                    "source_host": "owned.example.com",
                    "source_kind": "remote_policy",
                    "authorized_hosts": ["unrelated.example.net"],
                }
            ]
        },
    )

    result = run_remote_authority_chain(state, repo_root=tmp_path / "repo")
    assert result["promoted_count"] == 0
    assert result["candidate_count"] == 1

    chain = json.loads((state / "remote_authority_chain.json").read_text())
    row = chain["observations"][0]
    assert row["declared_host"] == "unrelated.example.net"
    assert row["decision"] == "authority_candidate"
    assert row["reason"] == "remote_declaration_has_no_independent_owner_basis_or_valid_signed_delegation"


def test_standing_exact_host_can_be_promoted_from_remote_declaration_then_join_chain(tmp_path: Path):
    state = tmp_path / "state"
    _policy(state, "owned.example.com")
    repo = tmp_path / "repo"
    _write(
        repo / "senju" / "state" / "standing_authorizations.json",
        {
            "schema": "senju-standing-authorization/v1",
            "records": [
                {
                    "issuer_kind": "owner_explicit",
                    "exact_hosts": ["partner.example.net"],
                    "allowed_methods": ["GET", "HEAD"],
                    "revoked": False,
                    "credential_scope": "none",
                    "destructive": False,
                }
            ],
        },
    )
    _write(
        state / "remote_authority_declarations.json",
        {
            "declarations": [
                {
                    "source_host": "owned.example.com",
                    "source_kind": "federation_member",
                    "members": ["partner.example.net"],
                },
                {
                    "source_host": "partner.example.net",
                    "source_kind": ".well-known",
                    "members": ["child.partner.example.net"],
                },
            ]
        },
    )

    result = run_remote_authority_chain(state, repo_root=repo)
    assert result["promoted_hosts"] == ["partner.example.net"]
    chain = json.loads((state / "remote_authority_chain.json").read_text())
    child = [x for x in chain["observations"] if x.get("declared_host") == "child.partner.example.net"][0]
    assert child["decision"] == "authority_candidate"


def test_unknown_remote_source_kind_is_recorded_but_not_promoted(tmp_path: Path):
    state = tmp_path / "state"
    _policy(state, "owned.example.com")
    _write(
        state / "remote_authority_declarations.json",
        {
            "declarations": [
                {
                    "source_host": "owned.example.com",
                    "source_kind": "random_web_text",
                    "hosts": ["b.owned.example.com"],
                }
            ]
        },
    )

    result = run_remote_authority_chain(state, repo_root=tmp_path / "repo")
    assert result["promoted_count"] == 0
    chain = json.loads((state / "remote_authority_chain.json").read_text())
    assert chain["observations"][0]["reason"] == "unsupported_remote_source_kind"


def test_cycles_terminate_without_fixed_depth_limit(tmp_path: Path):
    state = tmp_path / "state"
    _policy(state, "owned.example.com")
    _write(
        state / "remote_authority_declarations.json",
        {
            "declarations": [
                {"source_host": "owned.example.com", "source_kind": "remote_declaration", "members": ["b.owned.example.com"]},
                {"source_host": "b.owned.example.com", "source_kind": "remote_declaration", "members": ["owned.example.com"]},
            ]
        },
    )

    result = run_remote_authority_chain(state, repo_root=tmp_path / "repo")
    assert result["fixed_chain_depth_limit"] is None
    assert "b.owned.example.com" in result["promoted_hosts"]
