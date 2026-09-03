"""Bootstrap trusted production owner configuration into The World runtime state.

The unified loop persists generated state in ``.the-world-runtime`` across runs, while
owner-declared discovery/network policy lives in the checked-out repository under
``automation/codegen/meta_state``.  This module reconnects those two worlds at the start
of every run.

Only a fixed allowlist of declarative owner configuration is copied. Generated grants,
action queues, capability leases, replicas, receipts, checkpoints, and recovery output
are never imported as authority. The current trusted production checkout therefore wins
over stale cached runtime configuration without letting cached state mint or preserve
authority on its own.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

BOOTSTRAP_SCHEMA = "the-world-owner-runtime-bootstrap/v1"
REQUIRED_OWNER_CONFIG = frozenset({"discovery_policy.json", "meta_discovery_seed.json"})
TRUSTED_OWNER_CONFIG = (
    "discovery_policy.json",
    "meta_discovery_seed.json",
    "network_policy_envelope.json",
    "authorized_test_federation.json",
    "authority_review_policy.json",
    "human_intent_signals.json",
)


class ProductionStateBootstrapError(RuntimeError):
    """Raised when required trusted production owner configuration is unavailable."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionStateBootstrapError(f"invalid owner runtime config: {path.name}") from exc
    if not isinstance(value, dict):
        raise ProductionStateBootstrapError(f"owner runtime config must be an object: {path.name}")
    return value


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def bootstrap_owner_runtime_state(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    now: int | None = None,
) -> dict[str, Any]:
    """Overwrite runtime owner config from the trusted production checkout.

    Runtime-generated files are intentionally untouched. Missing optional config is
    recorded, while the discovery policy and owner seed are mandatory because the
    production loop cannot prove Discovery -> Authorization without them.
    """
    state = Path(state_dir)
    root = Path(repo_root)
    source = root / "automation" / "codegen" / "meta_state"
    state.mkdir(parents=True, exist_ok=True)

    missing_required = sorted(name for name in REQUIRED_OWNER_CONFIG if not (source / name).is_file())
    if missing_required:
        raise ProductionStateBootstrapError(
            f"required owner runtime config missing: {missing_required}"
        )

    copied: list[dict[str, Any]] = []
    optional_missing: list[str] = []
    for name in TRUSTED_OWNER_CONFIG:
        src = source / name
        if not src.is_file():
            if name in REQUIRED_OWNER_CONFIG:
                raise ProductionStateBootstrapError(f"required owner runtime config missing: {name}")
            optional_missing.append(name)
            continue

        payload = _load_object(src)
        rendered = _canonical_json(payload)
        destination = state / name
        destination.write_bytes(rendered)
        copied.append(
            {
                "name": name,
                "source": str(src.relative_to(root)),
                "destination": str(destination),
                "sha256": hashlib.sha256(rendered).hexdigest(),
            }
        )

    copied_names = {row["name"] for row in copied}
    required_present = REQUIRED_OWNER_CONFIG.issubset(copied_names)
    if not required_present:
        raise ProductionStateBootstrapError("required owner runtime config was not bootstrapped")

    receipt = {
        "schema": BOOTSTRAP_SCHEMA,
        "generated_at": int(time.time()) if now is None else int(now),
        "authority_source": "trusted_production_checkout",
        "source_directory": str(source.relative_to(root)),
        "required_files": sorted(REQUIRED_OWNER_CONFIG),
        "required_files_present": True,
        "copied_files": copied,
        "optional_missing": optional_missing,
        "generated_authority_imported": False,
        "runtime_cache_may_override_owner_policy": False,
        "stale_runtime_policy_replaced": True,
    }
    (state / "owner_runtime_bootstrap.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt
