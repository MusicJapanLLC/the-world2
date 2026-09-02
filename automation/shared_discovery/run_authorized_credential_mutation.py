from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from engine.authorized_credential_mutation import run_authorized_credential_mutation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan",
        default="automation/codegen/config/authorized_credential_mutation_plan.json",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--execute-if-enabled", action="store_true")
    args = parser.parse_args()

    execute = bool(args.execute)
    if args.execute_if_enabled:
        execute = os.environ.get("AUTHORIZED_TEST_MUTATION_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    result = run_authorized_credential_mutation(
        args.plan,
        repo_root=args.repo_root,
        state_dir=args.state,
        execute=execute,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
