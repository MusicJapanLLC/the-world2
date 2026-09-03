from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.authority_approval_progress import run_approval_progress


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance Authority approval progress state")
    parser.add_argument("--state", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_approval_progress(args.state, repo_root=args.repo_root)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
