"""CLI for the production AI Security Proposal closed loop."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from engine.security_proposal import (
    apply_proposal_to_state,
    evaluate_security_proposal,
    proposal_sha256,
)
from engine.standing_authority import resolve_standing_approval


def _load(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _github_json(url: str) -> Any:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "the-world-security-proposal-loop",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _event_pr_number() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_path:
        return 0
    event = _load(event_path, {})
    if not isinstance(event, dict):
        return 0
    pr = event.get("pull_request")
    if isinstance(pr, dict):
        return int(pr.get("number") or 0)
    return 0


def _associated_pr_number(repo: str, sha: str) -> int:
    if not repo or not sha:
        return 0
    rows = _github_json(
        f"https://api.github.com/repos/{repo}/commits/{urllib.parse.quote(sha, safe='')}/pulls"
    )
    if not isinstance(rows, list):
        return 0
    merged = [row for row in rows if isinstance(row, dict) and row.get("merged_at")]
    if not merged:
        return 0
    merged.sort(key=lambda row: str(row.get("merged_at") or ""), reverse=True)
    return int(merged[0].get("number") or 0)


def _github_external_approval(repo: str, pr_number: int, proposal_hash: str) -> dict[str, Any] | None:
    if not repo or pr_number <= 0:
        return None
    reviews = _github_json(f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews?per_page=100")
    if not isinstance(reviews, list):
        return None

    latest_by_user: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get("user")
        if not isinstance(user, dict):
            continue
        login = str(user.get("login") or "").strip()
        if not login:
            continue
        current = latest_by_user.get(login)
        stamp = str(review.get("submitted_at") or "")
        if current is None or stamp >= str(current.get("submitted_at") or ""):
            latest_by_user[login] = review

    trusted = []
    for login, review in latest_by_user.items():
        user = review.get("user") if isinstance(review.get("user"), dict) else {}
        if str(user.get("type") or "") != "User":
            continue
        if str(review.get("state") or "").upper() != "APPROVED":
            continue
        association = str(review.get("author_association") or "").upper()
        if association not in {"OWNER", "MEMBER", "COLLABORATOR"}:
            continue
        trusted.append((str(review.get("submitted_at") or ""), login, association))

    if not trusted:
        return None
    trusted.sort(reverse=True)
    _, reviewer, association = trusted[0]
    return {
        "approved": True,
        "source": "github_pull_request_review",
        "reviewer": reviewer,
        "reviewer_type": "User",
        "reviewer_association": association,
        "review_state": "APPROVED",
        "pull_request": pr_number,
        "proposal_sha256": proposal_hash,
    }


def _resolve_external_approval(proposal: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    proposal_hash = proposal_sha256(proposal)

    # Standing delegation is checked first. The caller chooses the envelope
    # directory; production workflows point this at the trusted base checkout,
    # never at candidate-controlled files.
    standing = resolve_standing_approval(
        proposal,
        args.standing_envelope_dir or None,
        proposal_hash,
    )
    if standing:
        return standing

    repo = str(args.github_repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    pr_number = int(args.github_pr_number or _event_pr_number() or 0)
    if not pr_number:
        sha = str(args.github_sha or os.environ.get("GITHUB_SHA") or "").strip()
        pr_number = _associated_pr_number(repo, sha)
    return _github_external_approval(repo, pr_number, proposal_hash)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate/apply AI Security Proposals")
    parser.add_argument("proposal", nargs="+")
    parser.add_argument("--state")
    parser.add_argument("--write-state")
    parser.add_argument("--decision-dir")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--github-pr-number", type=int, default=0)
    parser.add_argument("--github-repo", default="")
    parser.add_argument("--github-sha", default="")
    parser.add_argument("--standing-envelope-dir", default="")
    args = parser.parse_args()

    state = _load(args.state, {}) if args.state else {}
    decisions: list[dict[str, Any]] = []

    for proposal_path in args.proposal:
        proposal = _load(proposal_path, {})
        initial = evaluate_security_proposal(proposal)
        external_approval = None
        if initial.get("proposal_class") == "authority_expansion":
            external_approval = _resolve_external_approval(proposal, args)
        decision = evaluate_security_proposal(proposal, external_approval)
        decisions.append(decision)

        if args.decision_dir:
            out_dir = Path(args.decision_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            name = Path(proposal_path).stem + ".decision.json"
            (out_dir / name).write_text(
                json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        required_flag = "production_apply_eligible" if args.apply else "proposal_gate_eligible"
        if decision.get(required_flag) is not True:
            print(json.dumps(decision, ensure_ascii=False, indent=2))
            return 2

        if args.apply:
            state = apply_proposal_to_state(state, proposal, decision, external_approval)

    if args.apply and args.write_state:
        target = Path(args.write_state)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "schema": "the-world-security-proposal-loop/v5",
        "environment": "production",
        "closed_loop": True,
        "count": len(decisions),
        "all_ai_consensus_approved": all(bool(d.get("ai_consensus_approved")) for d in decisions),
        "all_self_approved": all(bool(d.get("self_approved")) for d in decisions),
        "all_production_apply_eligible": all(bool(d.get("production_apply_eligible")) for d in decisions),
        "delegated_activation_count": sum(1 for d in decisions if d.get("delegated_authority_activation")),
        "decisions": decisions,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
