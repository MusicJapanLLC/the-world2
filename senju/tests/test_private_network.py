from __future__ import annotations

import io

import pytest

from senju.private_network import (
    PrivateNetworkContactClient,
    PrivateNetworkContactError,
    PrivateNetworkPolicy,
)


class _Response:
    status = 200
    code = 200
    headers = {}

    def __init__(self, body: bytes = b"ok") -> None:
        self._body = io.BytesIO(body)

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)


def _policy(**kwargs) -> PrivateNetworkPolicy:
    return PrivateNetworkPolicy.from_targets(
        ["internal.example"],
        ["10.42.0.0/16"],
        **kwargs,
    )


def test_private_network_is_explicitly_enabled_by_factory() -> None:
    policy = _policy()
    assert policy.allow_private_network is True
    assert policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})


def test_rejects_broad_or_public_cidrs() -> None:
    for cidr in ["0.0.0.0/0", "8.8.8.0/24", "127.0.0.0/8", "169.254.0.0/16"]:
        with pytest.raises(PrivateNetworkContactError):
            PrivateNetworkPolicy.from_targets(["internal.example"], [cidr])


def test_rejects_loopback_and_link_local_even_if_resolver_returns_them() -> None:
    for address in ["127.0.0.1", "169.254.169.254"]:
        client = PrivateNetworkContactClient(
            _policy(),
            resolver=lambda host, port, value=address: (value,),
            opener=lambda request, timeout: _Response(),
        )
        with pytest.raises(PrivateNetworkContactError):
            client.contact("https://internal.example/")


def test_rejects_address_outside_explicit_private_cidr() -> None:
    client = PrivateNetworkContactClient(
        _policy(),
        resolver=lambda host, port: ("10.99.1.5",),
        opener=lambda request, timeout: _Response(),
    )
    with pytest.raises(PrivateNetworkContactError):
        client.contact("https://internal.example/")


def test_rejects_non_allowlisted_host() -> None:
    client = PrivateNetworkContactClient(
        _policy(),
        resolver=lambda host, port: ("10.42.1.5",),
        opener=lambda request, timeout: _Response(),
    )
    with pytest.raises(PrivateNetworkContactError):
        client.contact("https://other.example/")


def test_rejects_write_methods() -> None:
    client = PrivateNetworkContactClient(
        _policy(),
        resolver=lambda host, port: ("10.42.1.5",),
        opener=lambda request, timeout: _Response(),
    )
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        with pytest.raises(PrivateNetworkContactError):
            client.contact("https://internal.example/", method=method)


def test_rejects_credential_headers() -> None:
    client = PrivateNetworkContactClient(
        _policy(),
        resolver=lambda host, port: ("10.42.1.5",),
        opener=lambda request, timeout: _Response(),
    )
    for header in ["Authorization", "Cookie", "X-API-Key"]:
        with pytest.raises(PrivateNetworkContactError):
            client.contact("https://internal.example/", headers={header: "secret"})


def test_allows_exact_read_only_private_target() -> None:
    client = PrivateNetworkContactClient(
        _policy(),
        resolver=lambda host, port: ("10.42.1.5",),
        opener=lambda request, timeout: _Response(b"hello"),
    )
    receipt = client.contact("https://internal.example/health", method="GET")
    assert receipt.status == 200
    assert receipt.resolved_ips == ("10.42.1.5",)
    assert receipt.contacted_hosts == ("internal.example",)
    assert receipt.response_bytes == 5
