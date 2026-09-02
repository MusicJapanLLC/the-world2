"""Evolving active-test loop for an explicitly owned Senju web range.

This module is intentionally scoped to a persistent TrustedOwnerScope. It performs
same-origin discovery, bounded non-destructive query/control differentials, and
small dummy form writes with provider acknowledgement + best-effort readback.

The loop remembers which probe families produce useful counterexamples and biases
future cycles toward productive families while retaining exploration pressure.
It never expands authority to linked third-party hosts, guesses credentials,
performs denial-of-service/resource exhaustion, or persists on the target.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Iterable, Mapping

from .external import ContactResult, ExternalContactClient, ExternalContactError
from .trusted_scope import TrustedOwnerScope, TrustedScopeError

REPORT_SCHEMA = "senju-owned-range-active/v1"
MEMORY_SCHEMA = "senju-owned-range-active-memory/v1"

PROBE_FAMILIES = (
    "reflection_canary",
    "role_diff",
    "debug_diff",
    "id_diff",
    "mode_diff",
    "case_diff",
    "duplicate_param",
    "method_diff",
)

SENSITIVE_FIELD_HINTS = (
    "password",
    "passwd",
    "passcode",
    "credit",
    "card",
    "cvv",
    "payment",
    "otp",
    "totp",
    "secret",
    "private_key",
    "ssn",
)
FORM_HINTS = (
    "contact",
    "feedback",
    "message",
    "inquiry",
    "support",
    "test",
    "dummy",
    "comment",
)
PRIVILEGE_HINTS = ("admin", "internal", "dashboard", "staff", "owner", "private")


class OwnedRangeError(RuntimeError):
    pass


@dataclass
class ProbeStats:
    attempts: int = 0
    interesting_hits: int = 0
    failures: int = 0
    last_reason: str = ""

    @property
    def hit_rate(self) -> float:
        return self.interesting_hits / self.attempts if self.attempts else 0.0


@dataclass
class OwnedRangeMemory:
    cycles: int = 0
    families: dict[str, ProbeStats] = field(default_factory=dict)
    last_write_at: dict[str, str] = field(default_factory=dict)

    def stats(self, family: str) -> ProbeStats:
        return self.families.setdefault(family, ProbeStats())

    def record_probe(self, family: str, *, interesting: bool, failed: bool, reason: str = "") -> None:
        stats = self.stats(family)
        stats.attempts += 1
        stats.interesting_hits += int(bool(interesting))
        stats.failures += int(bool(failed))
        if reason:
            stats.last_reason = reason[:240]

    def family_score(self, family: str) -> float:
        stats = self.stats(family)
        novelty = 1.0 / (1.0 + stats.attempts)
        reward = 2.6 * stats.hit_rate
        failure_penalty = min(0.8, stats.failures * 0.08)
        return round(1.0 + novelty + reward - failure_penalty, 4)

    def can_write(self, key: str, *, now: dt.datetime, cooldown_seconds: int) -> bool:
        raw = self.last_write_at.get(key)
        if not raw:
            return True
        try:
            previous = dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError:
            return True
        return (now - previous).total_seconds() >= max(0, cooldown_seconds)

    def record_write(self, key: str, *, now: dt.datetime) -> None:
        self.last_write_at[key] = now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MEMORY_SCHEMA,
            "cycles": self.cycles,
            "families": {
                key: asdict(value) | {"hit_rate": round(value.hit_rate, 4)}
                for key, value in sorted(self.families.items())
            },
            "last_write_at": dict(sorted(self.last_write_at.items())),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "OwnedRangeMemory":
        if not raw or raw.get("schema") != MEMORY_SCHEMA:
            return cls()
        memory = cls(cycles=max(0, int(raw.get("cycles") or 0)))
        families = raw.get("families") or {}
        if isinstance(families, Mapping):
            for family, value in families.items():
                if family not in PROBE_FAMILIES or not isinstance(value, Mapping):
                    continue
                memory.families[family] = ProbeStats(
                    attempts=max(0, int(value.get("attempts") or 0)),
                    interesting_hits=max(0, int(value.get("interesting_hits") or 0)),
                    failures=max(0, int(value.get("failures") or 0)),
                    last_reason=str(value.get("last_reason") or "")[:240],
                )
        writes = raw.get("last_write_at") or {}
        if isinstance(writes, Mapping):
            memory.last_write_at = {str(k): str(v) for k, v in writes.items()}
        return memory


@dataclass(frozen=True)
class FormField:
    name: str
    field_type: str = "text"
    value: str = ""


@dataclass(frozen=True)
class FormSpec:
    source_url: str
    action_url: str
    method: str
    fields: tuple[FormField, ...]

    @property
    def key(self) -> str:
        names = ",".join(sorted(field.name for field in self.fields))
        return hashlib.sha256(f"{self.action_url}|{names}".encode("utf-8")).hexdigest()[:20]


class _DiscoveryParser(HTMLParser):
    def __init__(self, source_url: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.links: list[str] = []
        self.forms: list[FormSpec] = []
        self._form_action: str | None = None
        self._form_method: str = "GET"
        self._fields: list[FormField] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(k).lower(): "" if v is None else str(v) for k, v in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = self._attrs(attrs)
        tag = tag.lower()
        if tag in {"a", "link"} and data.get("href"):
            self.links.append(data["href"])
            return
        if tag == "form":
            self._form_action = data.get("action") or self.source_url
            self._form_method = (data.get("method") or "GET").upper()
            self._fields = []
            return
        if self._form_action is None:
            return
        if tag == "input" and data.get("name"):
            self._fields.append(
                FormField(
                    name=data["name"],
                    field_type=(data.get("type") or "text").lower(),
                    value=data.get("value") or "",
                )
            )
        elif tag in {"textarea", "select"} and data.get("name"):
            self._fields.append(FormField(name=data["name"], field_type=tag, value=""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "form" or self._form_action is None:
            return
        action = urllib.parse.urljoin(self.source_url, self._form_action)
        self.forms.append(
            FormSpec(
                source_url=self.source_url,
                action_url=action,
                method=self._form_method,
                fields=tuple(self._fields),
            )
        )
        self._form_action = None
        self._form_method = "GET"
        self._fields = []


def _clean_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise OwnedRangeError(f"unsupported URL: {url!r}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")


def _same_origin(url: str, base_url: str) -> bool:
    a = urllib.parse.urlsplit(url)
    b = urllib.parse.urlsplit(base_url)
    return a.scheme.lower() == b.scheme.lower() == "https" and (a.hostname or "").lower() == (b.hostname or "").lower()


def _with_param(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    pairs = [(k, v) for k, v in pairs if k != key]
    pairs.append((key, value))
    query = urllib.parse.urlencode(pairs, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", query, ""))


def _with_case_param(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    pairs.append((key, value))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", urllib.parse.urlencode(pairs, doseq=True), "")
    )


def _with_duplicate(url: str, key: str, values: tuple[str, str]) -> str:
    parsed = urllib.parse.urlsplit(url)
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if k != key]
    pairs.extend([(key, values[0]), (key, values[1])])
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", urllib.parse.urlencode(pairs, doseq=True), "")
    )


def _probe_variants(url: str, family: str, *, marker: str, cycle: int) -> list[tuple[str, str, str]]:
    if family == "reflection_canary":
        value = f"{marker}_<>\"'"
        return [("canary", "GET", _with_param(url, "senju_probe", value))]
    if family == "role_diff":
        pairs = (("user", "admin"), ("guest", "staff"), ("viewer", "owner"))
        a, b = pairs[cycle % len(pairs)]
        return [(a, "GET", _with_param(url, "role", a)), (b, "GET", _with_param(url, "role", b))]
    if family == "debug_diff":
        pairs = (("0", "1"), ("false", "true"), ("off", "on"))
        a, b = pairs[cycle % len(pairs)]
        return [(a, "GET", _with_param(url, "debug", a)), (b, "GET", _with_param(url, "debug", b))]
    if family == "id_diff":
        start = 1 + (cycle % 7)
        return [
            (str(start), "GET", _with_param(url, "id", str(start))),
            (str(start + 1), "GET", _with_param(url, "id", str(start + 1))),
        ]
    if family == "mode_diff":
        pairs = (("public", "internal"), ("summary", "full"), ("viewer", "editor"))
        a, b = pairs[cycle % len(pairs)]
        key = "view" if cycle % 2 == 0 else "mode"
        return [(a, "GET", _with_param(url, key, a)), (b, "GET", _with_param(url, key, b))]
    if family == "case_diff":
        return [
            ("role", "GET", _with_param(url, "role", "admin")),
            ("Role", "GET", _with_case_param(url, "Role", "admin")),
        ]
    if family == "duplicate_param":
        return [
            ("user-admin", "GET", _with_duplicate(url, "role", ("user", "admin"))),
            ("admin-user", "GET", _with_duplicate(url, "role", ("admin", "user"))),
        ]
    if family == "method_diff":
        return [("HEAD", "HEAD", url), ("OPTIONS", "OPTIONS", url)]
    raise OwnedRangeError(f"unknown probe family: {family}")


def _result_record(label: str, method: str, url: str, result: ContactResult) -> dict[str, Any]:
    receipt = result.receipt
    return {
        "label": label,
        "method": method,
        "url": url,
        "success": True,
        "status": int(receipt.status),
        "provider_acknowledged": bool(receipt.provider_acknowledged),
        "final_url": receipt.final_url,
        "response_bytes": int(receipt.response_bytes),
        "response_sha256": receipt.response_sha256,
        "content_type": receipt.content_type,
        "body": result.body,
    }


def _failure_record(label: str, method: str, url: str, exc: Exception) -> dict[str, Any]:
    return {
        "label": label,
        "method": method,
        "url": url,
        "success": False,
        "status": None,
        "provider_acknowledged": False,
        "response_bytes": 0,
        "response_sha256": "",
        "content_type": None,
        "body": b"",
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
    }


def _body_text(row: Mapping[str, Any]) -> str:
    body = row.get("body") or b""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="ignore")
    return str(body)


def _analyze_probe(family: str, rows: list[dict[str, Any]], *, marker: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    successful = [row for row in rows if row.get("success")]
    if not successful:
        return False, ["all_requests_failed"]

    if family == "reflection_canary":
        text = _body_text(successful[0])
        if marker in text:
            reasons.append("reflection_canary_returned_in_response")
        return bool(reasons), reasons

    if len(successful) >= 2:
        a, b = successful[0], successful[1]
        if a.get("status") != b.get("status"):
            reasons.append(f"status_diff:{a.get('status')}->{b.get('status')}")
        size_a = int(a.get("response_bytes") or 0)
        size_b = int(b.get("response_bytes") or 0)
        delta = abs(size_a - size_b)
        if delta >= max(64, int(max(size_a, size_b, 1) * 0.15)):
            reasons.append(f"body_size_diff:{size_a}->{size_b}")
        if a.get("response_sha256") != b.get("response_sha256") and delta >= 32:
            reasons.append("response_hash_and_size_changed")
        text_a = _body_text(a).lower()
        text_b = _body_text(b).lower()
        privileged = [hint for hint in PRIVILEGE_HINTS if hint in text_b and hint not in text_a]
        if privileged:
            reasons.append("privilege_hint_diff:" + ",".join(privileged[:4]))
    return bool(reasons), reasons


def _safe_form(form: FormSpec, *, base_url: str) -> tuple[bool, str]:
    if form.method != "POST":
        return False, "method_not_post"
    if not _same_origin(form.action_url, base_url):
        return False, "cross_origin_action"
    names = " ".join(field.name.lower() for field in form.fields)
    types = {field.field_type.lower() for field in form.fields}
    if "password" in types or "file" in types:
        return False, "sensitive_field_type"
    if any(hint in names for hint in SENSITIVE_FIELD_HINTS):
        return False, "sensitive_field_name"
    context = " ".join(
        [
            urllib.parse.urlsplit(form.source_url).path.lower(),
            urllib.parse.urlsplit(form.action_url).path.lower(),
            names,
        ]
    )
    if not any(hint in context for hint in FORM_HINTS):
        return False, "not_dummy_contact_like"
    return True, "dummy_contact_like"


def _form_payload(form: FormSpec, marker: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for field in form.fields:
        name = field.name
        lname = name.lower()
        ftype = field.field_type.lower()
        if ftype in {"submit", "button", "reset", "image"}:
            continue
        if ftype == "hidden" and field.value:
            payload[name] = field.value
        elif ftype in {"checkbox", "radio"}:
            payload[name] = field.value or "on"
        elif "email" in lname or ftype == "email":
            payload[name] = f"senju+{marker.lower()}@example.invalid"
        elif any(token in lname for token in ("message", "comment", "inquiry", "body", "detail", "note")):
            payload[name] = f"SENJU authorized dummy test {marker}"
        elif any(token in lname for token in ("name", "company", "title", "subject")):
            payload[name] = f"SENJU TEST {marker}"
        else:
            payload[name] = marker
    if not payload:
        payload["senju_probe"] = marker
    return payload


def _sanitize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "body"}


class OwnedRangeActiveRunner:
    def __init__(
        self,
        scope: TrustedOwnerScope,
        *,
        base_url: str,
        client: ExternalContactClient | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.scope = scope
        self.base_url = _clean_url(base_url)
        if not self.scope.allows_url(self.base_url):
            raise OwnedRangeError("base_url is outside trusted owner scope")
        if _host(self.base_url) not in self.scope.domain_roots:
            raise OwnedRangeError("active loop requires an exact trusted domain root")
        policy = self.scope.policy_for_url(self.base_url, method="GET")
        self.client = client or ExternalContactClient(policy)
        self._sleep = sleeper or time.sleep
        self._interval = 1.0 / max(0.1, self.scope.max_rps)
        self._request_count = 0

    def _contact(
        self,
        label: str,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.scope.allows_url(url):
            raise OwnedRangeError(f"URL escaped trusted scope: {url}")
        self.scope.policy_for_url(url, method=method)
        try:
            result = self.client.contact_with_body(
                url,
                method=method,
                body=body,
                headers=dict(headers or {}),
            )
            row = _result_record(label, method, url, result)
        except (ExternalContactError, OSError, TimeoutError, TrustedScopeError) as exc:
            row = _failure_record(label, method, url, exc)
        self._request_count += 1
        self._sleep(self._interval)
        return row

    def _crawl(self, *, max_pages: int) -> tuple[list[dict[str, Any]], list[FormSpec], list[str]]:
        standard = (
            self.base_url,
            urllib.parse.urljoin(self.base_url, "/scope.json"),
            urllib.parse.urljoin(self.base_url, "/.well-known/security.txt"),
            urllib.parse.urljoin(self.base_url, "/robots.txt"),
        )
        queue: list[str] = []
        for url in standard:
            clean = _clean_url(url)
            if clean not in queue:
                queue.append(clean)
        seen: set[str] = set()
        pages: list[dict[str, Any]] = []
        forms: list[FormSpec] = []
        external_links: list[str] = []

        while queue and len(pages) < max(1, max_pages):
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            row = self._contact("crawl", "GET", url, headers={"Accept": "text/html,application/json,text/plain,*/*"})
            body = row.get("body") or b""
            discovered = 0
            form_count = 0
            if row.get("success") and "text/html" in str(row.get("content_type") or "").lower():
                parser = _DiscoveryParser(url)
                parser.feed(bytes(body).decode("utf-8", errors="ignore"))
                for raw in parser.links:
                    absolute = urllib.parse.urljoin(url, raw)
                    try:
                        clean = _clean_url(absolute)
                    except OwnedRangeError:
                        continue
                    if _same_origin(clean, self.base_url):
                        if clean not in seen and clean not in queue:
                            queue.append(clean)
                            discovered += 1
                    elif clean not in external_links:
                        external_links.append(clean)
                for form in parser.forms:
                    if _same_origin(form.action_url, self.base_url):
                        forms.append(form)
                    elif form.action_url not in external_links:
                        external_links.append(form.action_url)
                form_count = len(parser.forms)
            pages.append(
                _sanitize_row(row)
                | {
                    "discovered_internal_links": discovered,
                    "discovered_forms": form_count,
                }
            )
        return pages, forms, external_links

    def _run_probes(
        self,
        urls: list[str],
        memory: OwnedRangeMemory,
        *,
        marker: str,
        seed: int,
        max_probe_requests: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        rng = random.Random(seed + memory.cycles * 7919)
        scores = {
            family: memory.family_score(family) + rng.random() * 0.45
            for family in PROBE_FAMILIES
        }
        ranked = sorted(PROBE_FAMILIES, key=lambda family: (-scores[family], family))
        # Keep some deliberate exploration even after one family becomes dominant.
        if memory.cycles % 3 == 2:
            rng.shuffle(ranked)
        selected = ranked[: min(len(ranked), 8)]

        probes: list[dict[str, Any]] = []
        counterexamples: list[dict[str, Any]] = []
        used = 0
        pages = urls or [self.base_url]

        for index, family in enumerate(selected):
            if used >= max_probe_requests:
                break
            url = pages[index % len(pages)]
            variants = _probe_variants(url, family, marker=marker, cycle=memory.cycles)
            rows: list[dict[str, Any]] = []
            for label, method, variant_url in variants:
                if used >= max_probe_requests:
                    break
                rows.append(self._contact(label, method, variant_url))
                used += 1
            interesting, reasons = _analyze_probe(family, rows, marker=marker)
            failed = bool(rows) and not any(row.get("success") for row in rows)
            memory.record_probe(
                family,
                interesting=interesting,
                failed=failed,
                reason=";".join(reasons) or ("request_failed" if failed else "no_material_diff"),
            )
            probes.append(
                {
                    "family": family,
                    "family_score_before": round(scores[family], 4),
                    "interesting": interesting,
                    "reasons": reasons,
                    "requests": [_sanitize_row(row) for row in rows],
                }
            )
            if interesting:
                counterexamples.append(
                    {
                        "kind": "owned_range_control_counterexample",
                        "surface": urllib.parse.urlsplit(url).path or "/",
                        "target": url,
                        "probe": family,
                        "reason": ";".join(reasons)[:500],
                        "authorized_scope": self.scope.scope_id,
                    }
                )
        return probes, counterexamples, selected

    def _run_writes(
        self,
        forms: Iterable[FormSpec],
        memory: OwnedRangeMemory,
        *,
        marker: str,
        now: dt.datetime,
        max_writes: int,
        write_cooldown_seconds: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        writes: list[dict[str, Any]] = []
        counterexamples: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for form in forms:
            if len(writes) >= max(0, max_writes):
                break
            if form.key in seen_keys:
                continue
            seen_keys.add(form.key)
            safe, reason = _safe_form(form, base_url=self.base_url)
            if not safe:
                continue
            if not memory.can_write(form.key, now=now, cooldown_seconds=write_cooldown_seconds):
                writes.append(
                    {
                        "form_key": form.key,
                        "source_url": form.source_url,
                        "action_url": form.action_url,
                        "attempted": False,
                        "skip_reason": "write_cooldown",
                    }
                )
                continue

            payload = _form_payload(form, marker)
            body = urllib.parse.urlencode(payload).encode("utf-8")
            post = self._contact(
                "dummy-write",
                "POST",
                form.action_url,
                body=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "text/html,application/json,text/plain,*/*",
                    "X-Senju-Authorized-Test": marker,
                },
            )
            memory.record_write(form.key, now=now)
            provider_ack = bool(post.get("provider_acknowledged"))
            post_echo = marker in _body_text(post)
            readbacks: list[dict[str, Any]] = []
            independent = False

            candidates: list[str] = []
            final_url = str(post.get("final_url") or "")
            if final_url and _same_origin(final_url, self.base_url):
                candidates.append(_clean_url(final_url))
            if form.source_url not in candidates:
                candidates.append(form.source_url)
            for readback_url in candidates[:2]:
                row = self._contact("write-readback", "GET", readback_url)
                found = marker in _body_text(row)
                independent = independent or found
                readbacks.append(_sanitize_row(row) | {"marker_found": found})

            write = {
                "form_key": form.key,
                "source_url": form.source_url,
                "action_url": form.action_url,
                "attempted": True,
                "provider_acknowledged": provider_ack,
                "status": post.get("status"),
                "post_response_echo": post_echo,
                "independent_readback": independent,
                "readbacks": readbacks,
                "field_names": sorted(payload),
            }
            writes.append(write)

            if not provider_ack:
                counterexamples.append(
                    {
                        "kind": "owned_range_write_reliability",
                        "surface": urllib.parse.urlsplit(form.action_url).path or "/",
                        "target": form.action_url,
                        "probe": "dummy_form_write",
                        "reason": "authorized dummy POST was not provider-acknowledged",
                        "authorized_scope": self.scope.scope_id,
                    }
                )
            elif not independent and not post_echo:
                counterexamples.append(
                    {
                        "kind": "owned_range_readback_gap",
                        "surface": urllib.parse.urlsplit(form.action_url).path or "/",
                        "target": form.action_url,
                        "probe": "dummy_form_write",
                        "reason": "provider acknowledged write but marker was not independently observable",
                        "authorized_scope": self.scope.scope_id,
                    }
                )
        return writes, counterexamples

    def run(
        self,
        *,
        memory_data: Mapping[str, Any] | None = None,
        max_pages: int = 18,
        max_probe_requests: int = 24,
        max_writes: int = 3,
        write_cooldown_seconds: int = 3600,
        seed: int = 20260831,
        now: dt.datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        memory = OwnedRangeMemory.from_mapping(memory_data)
        marker = f"SENJU_{current.strftime('%Y%m%dT%H%M%S')}_{memory.cycles:04d}"

        pages, forms, external_links = self._crawl(max_pages=max_pages)
        probe_urls = [str(page.get("url") or "") for page in pages if page.get("success") and page.get("url")]
        probes, probe_counterexamples, selected = self._run_probes(
            probe_urls,
            memory,
            marker=marker,
            seed=seed,
            max_probe_requests=max_probe_requests,
        )
        writes, write_counterexamples = self._run_writes(
            forms,
            memory,
            marker=marker,
            now=current,
            max_writes=max_writes,
            write_cooldown_seconds=write_cooldown_seconds,
        )
        memory.cycles += 1
        counterexamples = probe_counterexamples + write_counterexamples

        family_state = {
            family: {
                "score": memory.family_score(family),
                "attempts": memory.stats(family).attempts,
                "interesting_hits": memory.stats(family).interesting_hits,
                "hit_rate": round(memory.stats(family).hit_rate, 4),
                "failures": memory.stats(family).failures,
                "last_reason": memory.stats(family).last_reason,
            }
            for family in PROBE_FAMILIES
        }
        normalized = {
            "authorized_host": _host(self.base_url),
            "pages": [(p.get("url"), p.get("status"), p.get("response_sha256")) for p in pages],
            "counterexamples": counterexamples,
            "writes": [
                {
                    "action_url": w.get("action_url"),
                    "attempted": w.get("attempted"),
                    "provider_acknowledged": w.get("provider_acknowledged"),
                    "independent_readback": w.get("independent_readback"),
                }
                for w in writes
            ],
            "families": family_state,
        }
        digest = hashlib.sha256(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]

        report = {
            "schema": REPORT_SCHEMA,
            "executed_at_utc": current.isoformat(timespec="seconds"),
            "scope_id": self.scope.scope_id,
            "owner": self.scope.owner,
            "base_url": self.base_url,
            "authorized_host": _host(self.base_url),
            "same_origin_only": True,
            "authority_self_expansion": False,
            "network_io": True,
            "destructive_requests": False,
            "credential_guessing": False,
            "denial_of_service": False,
            "request_count": self._request_count,
            "pages_discovered": len(pages),
            "forms_discovered": len(forms),
            "external_links_skipped": external_links[:40],
            "probe_requests_budget": max_probe_requests,
            "selected_probe_families": selected,
            "probe_family_state": family_state,
            "probes": probes,
            "writes": writes,
            "write_attempts": sum(1 for w in writes if w.get("attempted")),
            "write_provider_acks": sum(1 for w in writes if w.get("provider_acknowledged")),
            "independent_readbacks": sum(1 for w in writes if w.get("independent_readback")),
            "counterexamples": counterexamples,
            "counterexample_count": len(counterexamples),
            "evolution": {
                "memory_cycles": memory.cycles,
                "selection_policy": "reward productive families + retain exploration pressure",
                "next_family_ranking": sorted(PROBE_FAMILIES, key=lambda f: (-memory.family_score(f), f)),
            },
            "digest": digest,
        }
        return report, memory.to_dict()
