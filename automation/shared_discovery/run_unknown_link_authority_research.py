from __future__ import annotations

import argparse
import json

from engine.unknown_link_authority_research import run_unknown_link_authority_research


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the closed-loop unknown-link authority research lane")
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--chaos-rate", type=float, default=0.03)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_unknown_link_authority_research(args.state, chaos_rate=args.chaos_rate)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
