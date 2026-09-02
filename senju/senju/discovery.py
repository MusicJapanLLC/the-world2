"""HTML parsing, evidence extraction, and passive findings for Senju discovery.

Passively extracts title, links, forms, scripts, resource references, and security headers
from retrieved HTML/headers without mutating external state.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any, Mapping

from .external import ContactReceipt


@dataclass
class FormInfo:
    action: str
    method: str
    inputs: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PassiveObservation:
    category: str
    kind: str  # "confirmed_observation" or "unverified_hypothesis"
    title: str
    detail: str
    severity: str = "info"  # "info", "low", "medium", "high"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class HTMLPassiveExtractor(HTMLParser):
    """Passively parse HTML to extract links, forms, scripts, and resources."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title: str = ""
        self._in_title: bool = False
        self.links: list[dict[str, str]] = []
        self.forms: list[FormInfo] = []
        self.scripts: list[str] = []
        self.resources: list[str] = []
        self._current_form: FormInfo | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower == "title":
            self._in_title = True
        elif tag_lower == "a" and "href" in attr_dict:
            href = attr_dict["href"].strip()
            if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                full_url = urllib.parse.urljoin(self.base_url, href)
                self.links.append({
                    "raw_href": href,
                    "url": full_url,
                    "text": "",
                })
        elif tag_lower == "form":
            action = attr_dict.get("action", "").strip()
            full_action = urllib.parse.urljoin(self.base_url, action) if action else self.base_url
            method = attr_dict.get("method", "get").upper().strip()
            form = FormInfo(action=full_action, method=method)
            self.forms.append(form)
            self._current_form = form
        elif tag_lower == "input" and self._current_form is not None:
            inp_name = attr_dict.get("name", "").strip()
            inp_type = attr_dict.get("type", "text").lower().strip()
            self._current_form.inputs.append({"name": inp_name, "type": inp_type})
        elif tag_lower == "script" and "src" in attr_dict:
            src = attr_dict["src"].strip()
            if src:
                self.scripts.append(urllib.parse.urljoin(self.base_url, src))
        elif tag_lower == "img" and "src" in attr_dict:
            src = attr_dict["src"].strip()
            if src:
                self.resources.append(urllib.parse.urljoin(self.base_url, src))
        elif tag_lower == "link" and "href" in attr_dict:
            href = attr_dict["href"].strip()
            if href:
                self.resources.append(urllib.parse.urljoin(self.base_url, href))

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "title":
            self._in_title = False
        elif tag_lower == "form":
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        elif self.links and not self.links[-1]["text"]:
            self.links[-1]["text"] = data.strip()[:64]


SECURITY_HEADER_KEYS = (
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
)


def extract_security_headers(headers: Mapping[str, str] | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    if not headers:
        for k in SECURITY_HEADER_KEYS:
            out[k] = None
        return out

    normalized = {k.lower(): str(v) for k, v in headers.items()}
    for key in SECURITY_HEADER_KEYS:
        out[key] = normalized.get(key)
    return out


def analyze_passive_findings(
    receipt: ContactReceipt,
    extracted: HTMLPassiveExtractor,
    sec_headers: dict[str, str | None],
) -> tuple[list[PassiveObservation], list[PassiveObservation]]:
    """Separate confirmed passive observations from unverified hypotheses."""
    confirmed: list[PassiveObservation] = []
    hypotheses: list[PassiveObservation] = []

    # Security header observations (confirmed)
    if not sec_headers.get("strict-transport-security") and receipt.requested_url.startswith("https:"):
        confirmed.append(
            PassiveObservation(
                category="security_header",
                kind="confirmed_observation",
                title="Missing Strict-Transport-Security Header",
                detail="Target HTTPS response does not include Strict-Transport-Security (HSTS) header.",
                severity="low",
            )
        )

    if not sec_headers.get("content-security-policy"):
        confirmed.append(
            PassiveObservation(
                category="security_header",
                kind="confirmed_observation",
                title="Missing Content-Security-Policy Header",
                detail="Response lacks Content-Security-Policy header.",
                severity="low",
            )
        )

    if not sec_headers.get("x-frame-options"):
        confirmed.append(
            PassiveObservation(
                category="security_header",
                kind="confirmed_observation",
                title="Missing X-Frame-Options Header",
                detail="Response lacks X-Frame-Options clickjacking defense header.",
                severity="low",
            )
        )

    # Form observations
    for form in extracted.forms:
        password_inputs = [i for i in form.inputs if i.get("type") == "password"]
        if password_inputs:
            confirmed.append(
                PassiveObservation(
                    category="authentication",
                    kind="confirmed_observation",
                    title="Password Form Detected",
                    detail=f"Form at action '{form.action}' contains {len(password_inputs)} password input field(s).",
                    severity="info",
                )
            )
            # Unverified hypothesis
            hypotheses.append(
                PassiveObservation(
                    category="authentication",
                    kind="unverified_hypothesis",
                    title="Potential Authentication Endpoint",
                    detail=f"Form at action '{form.action}' may accept user credentials (untested).",
                    severity="info",
                )
            )

    # Resource hypotheses
    for script in extracted.scripts:
        if "api" in script.lower() or "v1" in script.lower():
            hypotheses.append(
                PassiveObservation(
                    category="client_script",
                    kind="unverified_hypothesis",
                    title="Potential API Client Bundle Script",
                    detail=f"Script reference '{script}' contains API keywords (unverified).",
                    severity="info",
                )
            )

    return confirmed, hypotheses


def parse_html_evidence(
    requested_url: str,
    receipt: ContactReceipt,
    html_content: str,
    selection_score: float,
    discovery_source: str,
    commit_sha: str = "",
    workflow_run_id: str = "",
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build structured evidence dictionary from ContactReceipt and raw HTML content."""
    extractor = HTMLPassiveExtractor(base_url=receipt.final_url)
    if html_content:
        try:
            extractor.feed(html_content)
        except Exception:
            pass

    header_map: dict[str, str] = {}
    if headers:
        header_map.update({str(k): str(v) for k, v in headers.items()})
    if receipt.content_type and "content-type" not in {k.lower() for k in header_map}:
        header_map["content-type"] = receipt.content_type

    sec_headers = extract_security_headers(header_map)

    confirmed, hypotheses = analyze_passive_findings(receipt, extractor, sec_headers)

    # Deduplicate discovered candidate links
    seen_urls: set[str] = set()
    discovered_candidates: list[dict[str, str]] = []
    for link in extractor.links:
        u = link["url"]
        if u not in seen_urls:
            seen_urls.add(u)
            discovered_candidates.append(link)

    return {
        "schema": "senju-discovery-evidence/v1",
        "discovery": {
            "source": discovery_source,
            "selection_score": selection_score,
            "commit_sha": commit_sha,
            "workflow_run_id": workflow_run_id,
        },
        "contact": receipt.to_dict(),
        "html": {
            "title": extractor.title.strip(),
            "link_count": len(discovered_candidates),
            "form_count": len(extractor.forms),
            "script_count": len(extractor.scripts),
            "resource_count": len(extractor.resources),
            "forms": [asdict(f) for f in extractor.forms],
            "scripts": extractor.scripts[:20],
            "resources": extractor.resources[:20],
        },
        "security_headers": sec_headers,
        "passive_observations": [c.to_dict() for c in confirmed],
        "unverified_hypotheses": [h.to_dict() for h in hypotheses],
        "discovered_candidates": discovered_candidates[:50],
    }
