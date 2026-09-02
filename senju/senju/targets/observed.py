"""Observed external responses -> Senju arena targets.

This adapter is the coupling point between Senju's real outbound HTTP transport
and its RED/BLUE decision engine. A bounded GET/HEAD response is fingerprinted,
and that fingerprint deterministically shapes the synthetic arena surfaces.

Important truth boundary:
- the external HTTP response is real;
- the generated vulnerability surfaces are hypotheses for simulation, not claims
  that the contacted host is vulnerable;
- no exploit payload is sent by this adapter.
"""
from __future__ import annotations

import hashlib
import random
import urllib.parse

from ..external import ContactReceipt
from .base import ARCHETYPES, Surface, VULN_CLASSES, archetype_weight


def _infer_archetype(url: str, content_type: str | None) -> str:
    parsed = urllib.parse.urlsplit(url)
    ct = (content_type or "").lower()
    path = parsed.path.lower()
    if "json" in ct or path.startswith("/api/") or path == "/api":
        return "api"
    if any(token in path for token in ("login", "oauth", "auth", "signin")):
        return "auth_service"
    return "web_app"


class ObservedExternalTarget:
    """A simulated arena target whose shape is anchored to a real HTTP receipt."""

    def __init__(
        self,
        receipt: ContactReceipt,
        source_url: str,
        *,
        instance: int = 0,
        n_surfaces: int = 8,
    ) -> None:
        self.receipt = receipt
        self.source_url = source_url
        self.instance = int(instance)
        self.archetype = _infer_archetype(source_url, receipt.content_type)
        if self.archetype not in ARCHETYPES:
            self.archetype = "web_app"
        self.name = f"observed-{receipt.host}-{receipt.response_sha256[:10]}-{self.instance}"
        # Keep Arena access in-process: real network I/O happened before target creation.
        self.ref = f"sim://{self.name}"
        self._n = max(4, min(int(n_surfaces), 16))
        self._surfaces: list[Surface] = []
        self.reset()

    @property
    def observation_fingerprint(self) -> str:
        material = (
            f"{self.receipt.host}|{self.receipt.status}|{self.receipt.response_sha256}|"
            f"{self.receipt.content_type}|{self.receipt.response_bytes}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _rng(self) -> random.Random:
        seed_material = f"{self.observation_fingerprint}:{self.instance}"
        return random.Random(int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16))

    def reset(self) -> None:
        rng = self._rng()
        weights = [archetype_weight(self.archetype, v) for v in VULN_CLASSES]

        # A real response changes the synthetic difficulty landscape without being
        # interpreted as proof of any vulnerability.
        status_bias = 0.08 if self.receipt.status in {401, 403} else 0.0
        size_bias = min(0.08, self.receipt.response_bytes / (1024 * 1024 * 8))
        self._surfaces = []
        for i in range(self._n):
            vuln = rng.choices(VULN_CLASSES, weights=weights, k=1)[0]
            difficulty = rng.uniform(0.22, 0.92) + status_bias + size_bias
            self._surfaces.append(
                Surface(
                    name=f"{self.name}:hypothesis-{i}",
                    vuln_class=vuln,
                    difficulty=round(max(0.05, min(difficulty, 0.98)), 3),
                    mitigated=False,
                    monitored=False,
                )
            )

    def surfaces(self) -> list[Surface]:
        return self._surfaces

    def evidence(self) -> dict[str, object]:
        return {
            "schema": "senju-observed-target/v1",
            "source_url": self.source_url,
            "host": self.receipt.host,
            "http_status": self.receipt.status,
            "provider_acknowledged": self.receipt.provider_acknowledged,
            "response_sha256": self.receipt.response_sha256,
            "response_bytes": self.receipt.response_bytes,
            "content_type": self.receipt.content_type,
            "observation_fingerprint": self.observation_fingerprint,
            "archetype": self.archetype,
            "surface_count": len(self._surfaces),
            "surfaces_are_simulated_hypotheses": True,
            "real_exploit_executed": False,
        }
