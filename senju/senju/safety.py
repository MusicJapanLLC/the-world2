"""
senju.safety — Arena target_ref のスコープ制御。

外部HTTP(S)接触は `senju.external` が担当する。
Arena の target_ref 検査とネットワーク egress を混同しない。

方針:
- 通常運用は fail-closed。
- 仮想標的 / 明示許可したラボ参照だけを受理する。
- 明示許可されたHTTPSホストは、そのホスト配下の任意path/query/fragmentを受理する。
- フェデレーションでは、検証済みメンバーホスト集合を明示的に policy へ渡して相互リンクを許可する。
- HTMLリンクの存在だけでは新しいホストを自動認可しない。
"""
from __future__ import annotations

import ipaddress
import urllib.parse
from dataclasses import dataclass, field
from typing import Iterable


class ScopeViolation(RuntimeError):
    """許可スコープ外への操作を検出した場合に送出される。"""


SIMULATED_SCHEME = "sim://"
TEST_FEDERATION_ID = "the-world-security-test-federation-v1"
DEFAULT_AUTHORIZED_PUBLIC_LAB_HOSTS = frozenset({
    "kabeya-authorized-test-range.onrender.com",
})


def _normalize_hosts(hosts: Iterable[str]) -> set[str]:
    return {str(host).strip().rstrip(".").lower() for host in hosts if str(host).strip()}


def _is_lab_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _invalid_target_ref_reason(target_ref: str) -> str | None:
    if target_ref != target_ref.strip():
        return "標的参照の先頭または末尾に空白がある"
    if any(ord(char) < 32 or ord(char) == 127 for char in target_ref):
        return "標的参照に制御文字が含まれている"
    return None


def _authorized_https_host(target_ref: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(target_ref)
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return parsed.hostname.rstrip(".").lower()


@dataclass
class ScopePolicy:
    """Arena が扱う target_ref の受理ポリシー。"""

    allow_hosts: set[str] = field(default_factory=set)
    allow_simulated: bool = True
    allow_private_network: bool = False
    allow_abstract_external_refs: bool = False

    def with_hosts(self, hosts: Iterable[str]) -> "ScopePolicy":
        merged = _normalize_hosts(self.allow_hosts) | _normalize_hosts(hosts)
        return ScopePolicy(
            allow_hosts=merged,
            allow_simulated=self.allow_simulated,
            allow_private_network=self.allow_private_network,
            allow_abstract_external_refs=self.allow_abstract_external_refs,
        )


class ScopeGuard:
    """Arena のすべての target_ref が通過する検問所。"""

    def __init__(self, policy: ScopePolicy | None = None) -> None:
        self.policy = policy or ScopePolicy()
        self._violations: list[str] = []

    @property
    def violations(self) -> list[str]:
        return list(self._violations)

    def check(self, target_ref: str) -> None:
        reason = self._reject_reason(target_ref)
        if reason is not None:
            self._violations.append(f"{target_ref}: {reason}")
            raise ScopeViolation(
                f"スコープ違反: '{target_ref}' への参照は拒否されました ({reason})。"
            )

    def _reject_reason(self, target_ref: str) -> str | None:
        if not target_ref:
            return "空の標的参照"

        invalid_reason = _invalid_target_ref_reason(target_ref)
        if invalid_reason is not None:
            return invalid_reason

        if target_ref.startswith(SIMULATED_SCHEME):
            return None if self.policy.allow_simulated else "仮想標的が無効化されている"

        if target_ref.startswith("labnet:"):
            return None if self.policy.allow_private_network else "プライベートネット標的が無効化されている"

        normalized_ref = target_ref.rstrip(".").lower()
        normalized_allow_hosts = _normalize_hosts(self.policy.allow_hosts)
        if normalized_ref in normalized_allow_hosts:
            return None

        url_host = _authorized_https_host(target_ref)
        if url_host is not None and url_host in normalized_allow_hosts:
            return None

        if _is_lab_ip(target_ref):
            return None if self.policy.allow_private_network else "非公開IPだが allow_private_network が無効"

        if self.policy.allow_abstract_external_refs:
            return None

        return "許可リスト外（公開資産の可能性）。strict policyでは拒否"

    def is_allowed(self, target_ref: str) -> bool:
        return self._reject_reason(target_ref) is None


def default_lab_policy() -> ScopePolicy:
    """通常運用: 仮想標的 + Ownerが明示許可した公開ラボのみ許可する。"""
    return ScopePolicy(
        allow_hosts=set(DEFAULT_AUTHORIZED_PUBLIC_LAB_HOSTS),
        allow_simulated=True,
        allow_private_network=False,
        allow_abstract_external_refs=False,
    )


def federated_lab_policy(verified_member_hosts: Iterable[str] = ()) -> ScopePolicy:
    """Verified federation members only; callers must verify membership first."""
    return ScopePolicy(
        allow_hosts=set(DEFAULT_AUTHORIZED_PUBLIC_LAB_HOSTS) | _normalize_hosts(verified_member_hosts),
        allow_simulated=True,
        allow_private_network=False,
        allow_abstract_external_refs=False,
    )


def experimental_lab_policy(hosts: Iterable[str] = ()) -> ScopePolicy:
    """研究用: 抽象参照は許可するがネットワーク能力は付与しない。"""
    return ScopePolicy(
        allow_hosts=_normalize_hosts(hosts) | set(DEFAULT_AUTHORIZED_PUBLIC_LAB_HOSTS),
        allow_simulated=True,
        allow_private_network=True,
        allow_abstract_external_refs=True,
    )
