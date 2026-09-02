#!/usr/bin/env python3
"""THE WORLD Child Guild 50-member external input fleet.

Fifty fictional child personas receive independent public-web exploration assignments
per cycle. The fleet may follow links onto previously unseen public domains, but the
network surface here is intentionally read-only: HTTP(S) GET only, no credentials,
no private/link-local/loopback targets, no login bypass, no form submission, and no
third-party posting. Interaction opportunities can be *noticed* and turned into a
proposal for an authorized participation lane, but are not submitted by this scout.

Outputs are compact, auditable capsules intended for Child memory, R&D, and Senju.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UA = "TheWorld-ChildFleet/1.0 (+public-read-only; github.com/MusicJapanLLC/test)"
MAX_PAGE_BYTES = 360_000
MAX_FEED_BYTES = 2_000_000
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{3,32}|[ぁ-んァ-ン一-龯]{2,12}")
STOP = {
    "this", "that", "with", "from", "have", "your", "about", "into", "will",
    "http", "https", "html", "page", "read", "more", "child", "world", "guild",
    "true", "false", "none", "their", "there", "what", "when", "where", "which",
}

NAMES = [
    "Pixel","Momo","Byte","Pico","Nova","Kiki","Rin","Mochi","Zig","Nene",
    "Loop","Puku","Luna","Toto","Nico","Sora","Bibi","Kuma","Mimi","Robo",
    "Fizz","Poko","Mugi","Kero","Tama","Echo","Koko","Jelly","Pip","Yuzu",
    "Zero","Nori","Bam","Chibi","Wink","Ruru","Teki","Melo","Peta","Goma",
    "Raku","Nya","Mio","Qbit","Pompom","Zuzu","Lime","Taco","Mame","Orbit",
]


def load_json(path: str | Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def clean_text(value: str | None, limit: int = 900) -> str:
    if not value:
        return ""
    value = SCRIPT_RE.sub(" ", value)
    value = html.unescape(TAG_RE.sub(" ", value))
    return SPACE_RE.sub(" ", value).strip()[:limit]


def validate_url_syntax(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http/https public exploration is supported")
    if parsed.username or parsed.password:
        raise ValueError("credentials in URL are forbidden")
    if not parsed.hostname:
        raise ValueError("URL hostname is required")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc
    if port is not None and port not in {80, 443}:
        raise ValueError("only standard web ports are allowed")
    return parsed


def _assert_public_ip(value: str) -> None:
    ip = ipaddress.ip_address(value)
    if not ip.is_global:
        raise ValueError(f"non-public address blocked: {ip}")


def validate_public_url(url: str) -> urllib.parse.ParseResult:
    parsed = validate_url_syntax(url)
    host = parsed.hostname or ""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        _assert_public_ip(str(literal))
        return parsed

    infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ValueError("hostname resolved to no addresses")
    for address in addresses:
        _assert_public_ip(address)
    return parsed


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HostLimiter:
    """Small per-host pacing layer so 50 explorers do not become a flood."""

    def __init__(self, min_interval: float = 0.75) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                allowed = self._next.get(host, now)
                delay = max(0.0, allowed - now)
                if delay <= 0:
                    self._next[host] = now + self.min_interval
                    return
            time.sleep(min(delay, 0.25))


LIMITER = HostLimiter()
OPENER = urllib.request.build_opener(PublicRedirectHandler())


def fetch_public(url: str, max_bytes: int, accept: str, timeout: int = 12) -> tuple[bytes, str, str]:
    parsed = validate_public_url(url)
    LIMITER.wait(parsed.hostname or "unknown")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept}, method="GET")
    with OPENER.open(req, timeout=timeout) as res:
        if int(getattr(res, "status", 200)) < 200 or int(getattr(res, "status", 200)) >= 300:
            raise RuntimeError(f"HTTP {getattr(res, 'status', 'unknown')}")
        final_url = res.geturl()
        validate_public_url(final_url)
        content_type = (res.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        return res.read(max_bytes + 1)[:max_bytes], final_url, content_type


def child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for el in node.iter():
        if el.tag.rsplit("}", 1)[-1].lower() in names and el.text:
            return el.text.strip()
    return ""


def atom_link(node: ET.Element) -> str:
    for el in node.iter():
        if el.tag.rsplit("}", 1)[-1].lower() != "link":
            continue
        href = el.attrib.get("href", "").strip()
        rel = el.attrib.get("rel", "alternate")
        if href and rel in {"alternate", ""}:
            return href
    return ""


def parse_feed(raw: bytes, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    items: list[dict[str, Any]] = []
    for node in root.iter():
        local = node.tag.rsplit("}", 1)[-1].lower()
        if local not in {"item", "entry"}:
            continue
        title = clean_text(child_text(node, ("title",)), 240)
        link = child_text(node, ("link",)) if local == "item" else atom_link(node)
        if not link:
            link = atom_link(node)
        summary = clean_text(child_text(node, ("description", "summary", "content")), 520)
        if not title or not link:
            continue
        try:
            validate_url_syntax(link.strip())
        except Exception:
            continue
        uid = hashlib.sha256(f"{source.get('id')}|{link}".encode("utf-8")).hexdigest()[:20]
        items.append({
            "id": uid,
            "source_id": str(source.get("id", "unknown")),
            "category": str(source.get("category", "misc")),
            "title": title,
            "url": link.strip(),
            "summary": summary,
        })
        if len(items) >= limit:
            break
    return items


def gather_feed_pool(config: dict[str, Any], per_source: int = 24) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    pool: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in config.get("sources", []):
        if not isinstance(source, dict) or source.get("kind") != "rss":
            continue
        try:
            raw, _, _ = fetch_public(
                str(source["url"]),
                MAX_FEED_BYTES,
                "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9,*/*;q=0.1",
            )
            pool.extend(parse_feed(raw, source, per_source))
        except Exception as exc:
            errors.append({"source": str(source.get("id", "unknown")), "error": type(exc).__name__})

    unique: dict[str, dict[str, Any]] = {}
    for item in pool:
        unique.setdefault(item["url"], item)
    return list(unique.values()), errors


def remembered_concepts(memory: dict[str, Any], limit: int = 16) -> list[str]:
    counts = memory.get("concept_counts") if isinstance(memory, dict) else {}
    if not isinstance(counts, dict):
        return []
    ordered = sorted(counts.items(), key=lambda kv: (int(kv[1]), kv[0]), reverse=True)
    return [str(k) for k, _ in ordered[:limit]]


def item_score(item: dict[str, Any], child_id: str, seed: str, memory_terms: list[str]) -> float:
    hay = f"{item.get('title','')} {item.get('summary','')} {item.get('category','')}".lower()
    memory_match = sum(1 for term in memory_terms if term.lower() in hay) * 0.18
    novelty = int(hashlib.sha256(f"{seed}|{child_id}|{item['id']}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return memory_match + novelty


def build_assignments(pool: list[dict[str, Any]], seed: str, memory_terms: list[str]) -> list[dict[str, Any]]:
    if not pool:
        return [
            {"child": {"id": f"CHILD-{i:02d}", "name": NAMES[i - 1]}, "item": None}
            for i in range(1, 51)
        ]
    unused = set(range(len(pool)))
    assignments: list[dict[str, Any]] = []
    for i, name in enumerate(NAMES, start=1):
        child_id = f"CHILD-{i:02d}"
        candidates = unused if unused else set(range(len(pool)))
        idx = max(candidates, key=lambda n: item_score(pool[n], child_id, seed, memory_terms))
        unused.discard(idx)
        assignments.append({"child": {"id": child_id, "name": name}, "item": pool[idx]})
    return assignments


def extract_concepts(text: str, limit: int = 12) -> list[str]:
    counts = Counter(tok.lower() for tok in TOKEN_RE.findall(text) if tok.lower() not in STOP)
    return [token for token, _ in counts.most_common(limit)]


def page_title(raw_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_text, re.I | re.S)
    return clean_text(match.group(1), 240) if match else ""


def interaction_signal(raw_text: str) -> dict[str, Any]:
    lower = raw_text.lower()
    form = bool(re.search(r"<form\b", lower))
    participation_words = any(word in lower for word in ("comment", "reply", "discuss", "submit", "sign in to comment"))
    return {
        "public_interaction_signal": bool(form or participation_words),
        "form_seen": form,
        "participation_words_seen": participation_words,
        "write_attempt": "not_executed_on_third_party",
        "next_lane": "authorized-participation-or-owned-sandbox-only",
    }


def explore_one(assignment: dict[str, Any]) -> dict[str, Any]:
    child = assignment["child"]
    item = assignment.get("item")
    base = {
        "child": child,
        "status": "no_assignment" if item is None else "assigned",
        "source_id": (item or {}).get("source_id"),
        "category": (item or {}).get("category"),
        "feed_title": (item or {}).get("title"),
        "url": (item or {}).get("url"),
        "domain": None,
        "final_url": None,
        "page_title": None,
        "snippet": (item or {}).get("summary", ""),
        "concepts": extract_concepts(f"{(item or {}).get('title','')} {(item or {}).get('summary','')}", 10),
        "interaction": {
            "public_interaction_signal": False,
            "write_attempt": "not_executed_on_third_party",
            "next_lane": "authorized-participation-or-owned-sandbox-only",
        },
        "error": None,
    }
    if item is None:
        return base
    try:
        parsed = validate_url_syntax(str(item["url"]))
        base["domain"] = parsed.hostname
        raw, final_url, content_type = fetch_public(
            str(item["url"]), MAX_PAGE_BYTES, "text/html, text/plain, application/json;q=0.7,*/*;q=0.1"
        )
        if content_type and not (
            content_type.startswith("text/") or content_type in {"application/json", "application/xhtml+xml", "application/xml"}
        ):
            base["status"] = "skipped_non_text"
            base["final_url"] = final_url
            return base
        text = raw.decode("utf-8", errors="replace")
        plain = clean_text(text, 1800)
        base.update({
            "status": "fetched",
            "final_url": final_url,
            "page_title": page_title(text) or str(item.get("title", "")),
            "snippet": plain[:900] or str(item.get("summary", "")),
            "concepts": extract_concepts(f"{item.get('title','')} {plain}", 12),
            "interaction": interaction_signal(text),
        })
    except urllib.error.HTTPError as exc:
        base["status"] = "http_blocked"
        base["error"] = f"HTTPError:{exc.code}"
    except urllib.error.URLError:
        base["status"] = "network_error"
        base["error"] = "URLError"
    except Exception as exc:
        base["status"] = "blocked_or_invalid"
        base["error"] = type(exc).__name__
    return base


def summarize(results: list[dict[str, Any]], feed_errors: list[dict[str, str]], memory_terms: list[str]) -> dict[str, Any]:
    statuses = Counter(str(r.get("status")) for r in results)
    domains = Counter(str(r.get("domain")) for r in results if r.get("domain"))
    concepts = Counter()
    interaction_count = 0
    for result in results:
        concepts.update(result.get("concepts") or [])
        if (result.get("interaction") or {}).get("public_interaction_signal"):
            interaction_count += 1
    top = [name for name, _ in concepts.most_common(20)]
    hypotheses = [
        f"Explore whether '{concept}' changes the current robustness/learning/balance/efficiency assumptions."
        for concept in top[:8]
    ]
    return {
        "schema": "child-external-fleet/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fleet_size": 50,
        "mode": "public-read-only-open-domain-discovery",
        "results": results,
        "summary": {
            "status_counts": dict(statuses),
            "distinct_domains": len(domains),
            "top_domains": domains.most_common(12),
            "top_concepts": top,
            "remembered_concepts_used": memory_terms[:12],
            "public_interaction_signals": interaction_count,
            "feed_errors": feed_errors,
            "research_hypotheses": hypotheses,
        },
        "rnd_capsule": {
            "top_concepts": top[:12],
            "distinct_domains": len(domains),
            "status_counts": dict(statuses),
            "hypotheses": hypotheses[:6],
            "rule": "external observations are research stimuli, not execution authority or market validation",
        },
        "senju_capsule": {
            "top_concepts": top[:10],
            "distinct_domains": len(domains),
            "blocked_or_failed": sum(v for k, v in statuses.items() if k != "fetched"),
            "hypothesis_hints": hypotheses[:4],
            "rule": "context may alter technical hypotheses only; it does not grant target/network/write authority",
        },
        "network_rules": {
            "unknown_public_domains_allowed": True,
            "methods": ["GET"],
            "credentials": False,
            "private_networks": False,
            "login_bypass": False,
            "third_party_write": False,
            "interaction_discovery": True,
            "authorized_write_lane_can_be_proposed": True,
        },
    }


def render(fleet: dict[str, Any]) -> str:
    s = fleet["summary"]
    lines = [
        "# THE WORLD — Child Guild External Fleet",
        "",
        f"**Fleet:** {fleet['fleet_size']} fictional child explorers",
        f"**Mode:** `{fleet['mode']}`",
        f"**Distinct domains:** {s['distinct_domains']}",
        f"**Statuses:** {json.dumps(s['status_counts'], ensure_ascii=False)}",
        f"**Top concepts:** {', '.join(s['top_concepts'][:12]) or 'none'}",
        f"**Public interaction signals noticed:** {s['public_interaction_signals']}",
        "",
        "## R&D / Senju handoff",
    ]
    for hypothesis in s["research_hypotheses"][:6]:
        lines.append(f"- {hypothesis}")
    lines += [
        "",
        "Unknown public domains may be explored read-only. Third-party write surfaces may be noticed, but this fleet does not submit to them; proposals are routed to authorized participation or owned sandboxes.",
        "",
        "## Sample discoveries",
    ]
    for result in fleet["results"][:12]:
        lines.append(
            f"- **{result['child']['name']}** / {result.get('status')} / {result.get('domain') or '-'} / {result.get('page_title') or result.get('feed_title') or 'no title'}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="company-society/child_guild.json")
    ap.add_argument("--sources", default="outside-world/sources.json")
    ap.add_argument("--memory", default="child-guild-memory.json")
    ap.add_argument("--seed", default="")
    ap.add_argument("--max-workers", type=int, default=10)
    ap.add_argument("--out", default="child-external-fleet.json")
    ap.add_argument("--report", default="child-external-fleet.md")
    args = ap.parse_args()

    registry = load_json(args.registry, {})
    if registry.get("count") != 50 or len(registry.get("members") or []) != 50:
        raise ValueError("Child Guild fleet requires exactly 50 fictional members")
    config = load_json(args.sources, {})
    memory = load_json(args.memory, {})
    memory_terms = remembered_concepts(memory)
    seed = args.seed or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    pool, feed_errors = gather_feed_pool(config, per_source=24)
    assignments = build_assignments(pool, seed, memory_terms)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(16, args.max_workers))) as executor:
        future_map = {executor.submit(explore_one, assignment): assignment for assignment in assignments}
        for future in as_completed(future_map):
            results.append(future.result())
    results.sort(key=lambda r: r["child"]["id"])

    fleet = summarize(results, feed_errors, memory_terms)
    Path(args.out).write_text(json.dumps(fleet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(fleet), encoding="utf-8")
    print(json.dumps({
        "fleet": fleet["fleet_size"],
        "domains": fleet["summary"]["distinct_domains"],
        "statuses": fleet["summary"]["status_counts"],
        "concepts": fleet["summary"]["top_concepts"][:6],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
