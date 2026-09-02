"""Pre-authorized production guard envelope for immediate META/X-approved apply.

This module lets a production runtime apply an *exact* guard-change proposal
immediately after META/X/Senju consensus + META/X approval, but only when the
proposal id was pre-authorized by an external/bootstrap authority.

The envelope contains immutable exact proposal ids. Agents cannot widen it at
runtime by proposing new ids, and a near-match is not accepted.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable


class ProductionGuardEnvelopeError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class ProductionGuardEnvelope:
    """Immutable set of exact guard proposal ids approved for production fast-path."""

    approved_proposal_ids: frozenset[str]
    envelope_id: str = "production-guard-envelope-v1"

    @classmethod
    def create(
        cls,
        proposal_ids: Iterable[str],
        *,
        envelope_id: str = "production-guard-envelope-v1",
    ) -> "ProductionGuardEnvelope":
        normalized = frozenset(str(item).strip() for item in proposal_ids if str(item).strip())
        if not normalized:
            raise ProductionGuardEnvelopeError("production guard envelope cannot be empty")
        if not envelope_id.strip():
            raise ProductionGuardEnvelopeError("envelope_id cannot be empty")
        return cls(approved_proposal_ids=normalized, envelope_id=envelope_id.strip())

    def allows(self, proposal_id: str) -> bool:
        return str(proposal_id).strip() in self.approved_proposal_ids
