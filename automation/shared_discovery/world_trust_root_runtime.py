#!/usr/bin/env python3
"""Build the durable, provenance-bound WORLD trust-root checkpoint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEGEN = ROOT / "automation" / "codegen"
if str(CODEGEN) not in sys.path:
    sys.path.insert(0, str(CODEGEN))

from engine.world_trust_root_provenance_finalize import (  # noqa: E402
    build_provenance_finalized_world_checkpoint,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--shared-state-dir", default="/tmp/world/shared-discovery")
    parser.add_argument("--network-state-dir", default="/tmp/world/network-policy")
    parser.add_argument("--recovery-state-dir", default="/tmp/world/external-recovery")
    parser.add_argument("--continuity-state-dir", default="/tmp/world/production-continuity")
    parser.add_argument("--output-dir", default="/tmp/world/checkpoint")
    parser.add_argument("--previous-checkpoint-dir", default="/tmp/world/previous")
    parser.add_argument(
        "--config",
        default="automation/codegen/config/world-trust-root.json",
    )
    args = parser.parse_args()

    checkpoint = build_provenance_finalized_world_checkpoint(
        repo_root=args.repo_root,
        shared_state_dir=args.shared_state_dir,
        network_state_dir=args.network_state_dir,
        recovery_state_dir=args.recovery_state_dir,
        continuity_state_dir=args.continuity_state_dir,
        output_dir=args.output_dir,
        previous_checkpoint_dir=args.previous_checkpoint_dir,
        config_path=args.config,
    )
    print(json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
