from __future__ import annotations

import pytest

from senju.live_arena import readonly_observation_hosts


def test_url_host_is_automatically_authorized_for_read_observation() -> None:
    assert readonly_observation_hosts("https://example.com/path") == ("example.com",)


def test_extra_read_hosts_are_merged_into_one_scope() -> None:
    assert readonly_observation_hosts(
        "https://example.com/path",
        ["api.example.com", "cdn.example.com", "example.com"],
    ) == ("api.example.com", "cdn.example.com", "example.com")


def test_host_normalization_is_case_and_trailing_dot_tolerant() -> None:
    assert readonly_observation_hosts(
        "https://Example.COM./",
        ["API.Example.COM."],
    ) == ("api.example.com", "example.com")


def test_non_http_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="http/https"):
        readonly_observation_hosts("file:///tmp/x")


def test_missing_hostname_is_rejected() -> None:
    with pytest.raises(ValueError, match="no hostname"):
        readonly_observation_hosts("https:///path")
