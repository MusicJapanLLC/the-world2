"""CLI for recursive delegated Authority minting.

Examples:
  python senju/scripts/authority_mint.py list
  python senju/scripts/authority_mint.py mint --issuer META \
      --parent root:threat_intel_public --purpose "NVD-only research" \
      --hosts services.nvd.nist.gov --methods GET,HEAD --delegate

On first use, code-defined builtin Authority roots are seeded automatically.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENJU_DIR = ROOT / "senju"
sys.path.insert(0, str(SENJU_DIR))

from senju.authority_factory import (  # noqa: E402
    AuthorityMintRequest,
    AuthorityRegistry,
)

DEFAULT_REGISTRY = SENJU_DIR / "state" / "delegated_authorities.json"


def _csv(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    return frozenset(x.strip() for x in value.split(",") if x.strip())


def _tuple_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(x.strip() for x in value.split(",") if x.strip())


def _ensure_roots(registry: AuthorityRegistry, *, depth: int = 8) -> None:
    if registry.profiles:
        return
    registry.seed_builtin_roots(delegation_depth=depth)
    registry.save()


def main() -> int:
    parser = argparse.ArgumentParser(description="META/X/Senju delegated Authority minting")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="seed code-defined builtin root authorities")
    seed.add_argument("--depth", type=int, default=8)

    sub.add_parser("list", help="list registered authority profiles")

    mint = sub.add_parser("mint", help="mint a child authority from an existing parent")
    mint.add_argument("--issuer", required=True, choices=["META", "X", "Senju"])
    mint.add_argument("--parent", required=True)
    mint.add_argument("--purpose", required=True)
    mint.add_argument("--hosts")
    mint.add_argument("--methods")
    mint.add_argument("--rate", type=int)
    mint.add_argument("--timeout", type=float)
    mint.add_argument("--max-request-bytes", type=int)
    mint.add_argument("--max-response-bytes", type=int)
    mint.add_argument("--retries", type=int)
    mint.add_argument("--credential-scope", choices=["none", "public_token", "service_bearer"])
    mint.add_argument("--private-hosts")
    mint.add_argument("--private-cidrs")
    mint.add_argument("--allow-http", action="store_true")
    mint.add_argument("--follow-redirects", action="store_true")
    mint.add_argument("--allow-delete", action="store_true")
    mint.add_argument("--allow-private-network", action="store_true")
    mint.add_argument("--delegate", action="store_true", help="allow this child to mint a narrower descendant")

    args = parser.parse_args()
    registry = AuthorityRegistry.load(args.registry)

    if args.command == "seed":
        registry.seed_builtin_roots(delegation_depth=max(1, min(args.depth, 16)))
        registry.save()
        print(json.dumps({"ok": True, "profiles": len(registry.profiles), "registry": str(args.registry)}))
        return 0

    _ensure_roots(registry)

    if args.command == "list":
        print(json.dumps(registry.to_dict(), ensure_ascii=False, indent=2))
        return 0

    parent = registry.get(args.parent)
    request = AuthorityMintRequest(
        purpose=args.purpose,
        allow_hosts=_csv(args.hosts),
        allowed_methods=_csv(args.methods),
        allow_http=True if args.allow_http else None,
        follow_redirects=True if args.follow_redirects else None,
        allow_delete=True if args.allow_delete else None,
        rate_limit_per_minute=args.rate,
        timeout_seconds=args.timeout,
        max_request_bytes=args.max_request_bytes,
        max_response_bytes=args.max_response_bytes,
        retries=args.retries,
        credential_scope=args.credential_scope,
        allow_private_network=True if args.allow_private_network else None,
        private_hosts=_csv(args.private_hosts),
        private_cidrs=_tuple_csv(args.private_cidrs),
        can_delegate=bool(args.delegate),
    )
    child = registry.mint(parent.profile_id, request, issuer=args.issuer)
    registry.save()
    print(json.dumps({"ok": True, "profile": child.to_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
