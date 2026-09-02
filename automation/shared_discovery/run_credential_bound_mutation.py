from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.credential_bound_mutation_runtime import execute_credential_bound_mutations


def main() -> int:
    parser = argparse.ArgumentParser(description="Run credential-bound mutations for explicit synthetic test Authority")
    parser.add_argument("--state", default="automation/codegen/meta_state")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = execute_credential_bound_mutations(args.state, repo_root=args.repo_root)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
