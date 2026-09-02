#!/usr/bin/env python3
"""Fail-closed capability policy for privileged GitHub Actions in THE WORLD.

Every workflow that can write or mint an OIDC token must fit a reviewed capability
class. Unknown privilege is denied. The autonomous research fabric is deliberately a
separate, weaker class: it can obtain GitHub OIDC and write research evidence through
the allowlisted Supabase gateway, but it cannot write repository contents or dispatch
other workflows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(".github/workflows")
WORKFLOWS = {p.name: p.read_text(encoding="utf-8") for p in ROOT.glob("*.y*ml")}

WRITE_RE = re.compile(
    r"(?m)^\s+(contents|actions|checks|deployments|issues|packages|pull-requests|statuses|pages|id-token|copilot-requests):\s*write\s*$"
)
PIN_RE = re.compile(r"uses:\s+([^\s#]+)")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
GATEWAY_PROTOCOL_RE = re.compile(
    r'(?m)^GATEWAY_PROTOCOL\s*=\s*"oidc-repository-v(?P<version>\d+)-(?P<label>[a-z0-9][a-z0-9-]*)"\s*$'
)
UNSAFE = (
    "pull_request_target:", "workflow_run:", "issue_comment:", "repository_dispatch:",
    "runs-on: self-hosted", "permissions: write-all", "write-all",
    "git push --force", "git push -f", "--yolo", "--allow-all-tools",
)
MIN_GATEWAY_PROTOCOL_VERSION = 4
MAX_OWNED_STRESS_WRITES = 100
PUBLIC_FEED_ENDPOINT = "https://the-world-public-field-feed-zt5n2q.v2.appdeploy.ai/api/ingest"
PUBLIC_FEED_AUDIENCE = "the-world-public-field-feed"


def writes(body: str) -> set[str]:
    return {m.group(1) for m in WRITE_RE.finditer(body)}


def require(name: str, required: tuple[str, ...], forbidden: tuple[str, ...] = ()) -> str:
    body = WORKFLOWS.get(name, "")
    if not body:
        raise SystemExit(f"{name}: required privileged workflow is missing")
    for marker in required:
        if marker not in body:
            raise SystemExit(f"{name}: missing required guardrail: {marker}")
    for marker in forbidden:
        if marker in body:
            raise SystemExit(f"{name}: contains forbidden capability: {marker}")
    return body


def validate_global_safety() -> None:
    for name, body in WORKFLOWS.items():
        if name == "security-guard.yml":
            continue
        for token in UNSAFE:
            if token in body:
                raise SystemExit(f"{name}: forbidden workflow capability: {token}")
        lines = body.splitlines()
        for i, line in enumerate(lines):
            if "uses: actions/checkout@" in line:
                block = "\n".join(lines[i:i + 8])
                if "persist-credentials: false" not in block:
                    raise SystemExit(f"{name}:{i + 1}: checkout must discard credentials")
        for match in PIN_RE.finditer(body):
            ref = match.group(1)
            if ref.startswith("./"):
                continue
            if "@" not in ref:
                raise SystemExit(f"{name}: action has no immutable ref: {ref}")
            version = ref.rsplit("@", 1)[1]
            if not FULL_SHA.fullmatch(version):
                raise SystemExit(f"{name}: action is not pinned to a full commit SHA: {ref}")


def validate_gateway_client() -> None:
    client = Path("automation/world/task_worker.py").read_text(encoding="utf-8")
    for marker in (
        'AUDIENCE = "the-world-worker"', "ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        'method="POST"', "https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/the-world-github-worker",
        "_oidc_token()", 'Authorization": f"Bearer {_oidc_token()}"',
        'urllib.parse.urlencode({"audience": AUDIENCE})',
    ):
        if marker not in client:
            raise SystemExit(f"task_worker.py: missing OIDC/gateway invariant: {marker}")
    match = GATEWAY_PROTOCOL_RE.search(client)
    if not match or int(match.group("version")) < MIN_GATEWAY_PROTOCOL_VERSION:
        raise SystemExit("task_worker.py: gateway protocol version is missing/regressed")


def validate_pages_lanes() -> set[str]:
    lanes: set[str] = set()
    for name, body in WORKFLOWS.items():
        got = writes(body)
        if "pages" not in got:
            continue
        lanes.add(name)
        if got - {"pages", "id-token"}:
            raise SystemExit(f"{name}: Pages lane has unrelated writes: {sorted(got)}")
        require(name, (
            "contents: read", "pages: write", "id-token: write", "name: github-pages",
            "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
        ))
        if body.count("pages: write") != 1 or body.count("id-token: write") != 1:
            raise SystemExit(f"{name}: Pages/OIDC writes must occur exactly once")
        if "schedule:" in body:
            raise SystemExit(f"{name}: Pages deployment must not be scheduled")
        if "pull_request:" in body and "if: github.event_name != 'pull_request'" not in body:
            raise SystemExit(f"{name}: PR-triggered Pages workflow must suppress deployment on PR")
        if "push:" in body and "paths:" not in body:
            raise SystemExit(f"{name}: auto Pages deployment must be path-scoped")
    return lanes


def validate_task_worker() -> str:
    name = "the-world-task-worker.yml"
    body = require(name, (
        "contents: read", "actions: write", "id-token: write", "workflow_dispatch:", "schedule:",
        "cron: '*/5 * * * *'", "persist-credentials: false", "automation/world/task_worker.py",
        "gh workflow run", "Claim one personality-linked task",
        'gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${REVIEW_RUN_ID}"',
        "automation/world/external_feedback.py query --task-id", "task_worker.py finish-review --review /tmp/world-review.json",
    ), ("contents: write", "issues: write", "pull-requests: write", "packages: write", "deployments: write", "pages: write"))
    if writes(body) != {"actions", "id-token"}:
        raise SystemExit(f"{name}: unexpected writes {sorted(writes(body))}")
    if ("$" + "{{" + " secrets.") in body:
        raise SystemExit(f"{name}: long-lived Actions secrets are forbidden")
    for marker in ("CONCLUSION=", ".conclusion //", '<<<"$DATA"', "external=workflow=='world-reality-agency.yml'", "verified=workflow_ok", "external_feedback.py query --task-id"):
        if marker not in body:
            raise SystemExit(f"{name}: evidence reconciliation missing behavior: {marker}")
    if body.count("task_worker.py finish-review --review /tmp/world-review.json") < 2:
        raise SystemExit(f"{name}: verified and failed evidence paths must both close review")
    return name


def validate_reality_lane() -> str:
    name = "world-reality-agency.yml"
    body = require(name, (
        "contents: read", "actions: read", "issues: write", "id-token: write", "workflow_dispatch:", "schedule:", "persist-credentials: false",
        "outside-world/reality_policy.json", "outside-world/reality_gateway.py", "outside-world/public_feed_bridge.py", "--execute-owned-writes", "--limit 2",
    ), ("contents: write", "pull-requests: write", "packages: write", "deployments: write", "pages: write"))
    if writes(body) != {"issues", "id-token"}:
        raise SystemExit(f"{name}: reality write set drifted: {sorted(writes(body))}")
    if "pull_request:" in body:
        raise SystemExit(f"{name}: Reality Agency must never run with PR authority")
    policy = json.loads(Path("outside-world/reality_policy.json").read_text(encoding="utf-8"))
    actions, allow, browser, pulse = policy.get("actions") or {}, policy.get("allowlists") or {}, policy.get("browser") or {}, policy.get("pulse") or {}
    if actions.get("github_issue_own_repo") != "AUTO_ALLOWLIST" or actions.get("general_external_post") != "APPROVAL":
        raise SystemExit("reality policy: write boundary drifted")
    if actions.get("artifact_upload_owned_runtime") != "AUTO" or allow.get("github_repositories") != ["MusicJapanLLC/test"]:
        raise SystemExit("reality policy: ownership boundary drifted")
    if browser.get("respect_access_controls") is not True or browser.get("engagement_manipulation") is not False or browser.get("bulk_unsolicited_messaging") is not False:
        raise SystemExit("reality policy: browser safety invariants drifted")
    if int(pulse.get("max_publications_per_pulse", 0)) > 2:
        raise SystemExit("reality policy: public publication cap exceeds 2 per pulse")
    return name


def validate_research_oidc_lane() -> str:
    name = "the-world-autonomous-research-fabric.yml"
    body = require(name, (
        "contents: read", "actions: read", "id-token: write", "workflow_dispatch:", "schedule:", "cron: '*/15 * * * *'",
        "persist-credentials: false", "automation/world/task_worker.py research-config", "automation/world/task_worker.py record-research",
        "automation/world/research_fabric.py", "automation/world/test_research_fabric.py", "closed_model",
        "Validate research evidence boundary", "Preserve full research evidence",
    ), (
        "contents: write", "actions: write", "issues: write", "pull-requests: write", "packages: write", "deployments: write", "pages: write",
        "copilot-requests: write", "pull_request:", "gh workflow run", "git push ", "gh pr create",
    ))
    if writes(body) != {"id-token"}:
        raise SystemExit(f"{name}: research lane must have only OIDC write authority: {sorted(writes(body))}")
    if ("$" + "{{" + " secrets.") in body:
        raise SystemExit(f"{name}: research lane must not depend on long-lived Actions secrets")
    if body.count("record-research") != 1:
        raise SystemExit(f"{name}: research evidence must have exactly one bounded recording loop")
    engine = Path("automation/world/research_fabric.py").read_text(encoding="utf-8")
    for marker in (
        "No network, credentials, external targets, or real balances are modified here.", '"closed_model": True', "REPLICATE", "CROSS_POLLINATE",
        "random micro-search -> top-32 deep repeats -> best-vs-current unseen holdout",
    ):
        if marker not in engine:
            raise SystemExit(f"research_fabric.py: missing closed research invariant: {marker}")
    client = Path("automation/world/task_worker.py").read_text(encoding="utf-8")
    for marker in ("research-config", "record-research", '"authority": "exploration_geometry_only"'):
        if marker not in client:
            raise SystemExit(f"task_worker.py: missing research gateway/feedback invariant: {marker}")
    return name


def validate_experiment_oidc_lanes(page_lanes: set[str], excluded: set[str]) -> set[str]:
    lanes: set[str] = set()
    candidates = {name for name, body in WORKFLOWS.items() if "id-token" in writes(body)} - page_lanes - excluded
    secret_marker = "$" + "{{" + " secrets."
    for name in sorted(candidates):
        body = WORKFLOWS[name]
        got = writes(body)
        if got != {"contents", "id-token"}:
            raise SystemExit(f"{name}: unclassified OIDC write set: {sorted(got)}")
        for marker in (
            "contents: write", "actions: read", "id-token: write", "workflow_dispatch:", "schedule:", "persist-credentials: false",
            "automation/world/task_worker.py experiment-config", "automation/world/task_worker.py record-experiment",
            "senju/state/strategy.json", "CURRENT_BASE_SHA=", "force=false", "python -m senju.cli safety-check sim://",
            "python -m senju.cli safety-check https://example.com", "Base moved; safe promotion deferred",
        ):
            if marker not in body:
                raise SystemExit(f"{name}: OIDC experiment lane missing invariant: {marker}")
        if secret_marker in body or "pull_request:" in body:
            raise SystemExit(f"{name}: OIDC experiment lane authority is unsafe")
        if "git push " in body or "gh pr create" in body:
            raise SystemExit(f"{name}: promotion must use bounded GitHub ref API")
        if body.count("senju/state/strategy.json") < 2:
            raise SystemExit(f"{name}: promotion must re-read bounded strategy state")
        if "[.files[].filename]" not in body or "'[\"senju/state/strategy.json\"]'" not in body:
            raise SystemExit(f"{name}: promotion diff must prove strategy.json is the only changed file")
        lanes.add(name)
    return lanes


def _stress_write_count(body: str) -> int | None:
    match = re.search(r"for\s+\w+\s+in\s+\$\(seq\s+(\d+)\s+(\d+)\)", body)
    if not match:
        return None
    start, end = map(int, match.groups())
    if start < 1 or end < start:
        return None
    return end - start + 1


def validate_owned_issue_stress_lanes() -> set[str]:
    lanes: set[str] = set()
    for name, body in WORKFLOWS.items():
        if writes(body) != {"issues"} or name in ("world-reality-agency.yml", "jules-backlog-dispatch.yml", "jules-issue-router.yml", "the-world-external-write-router.yml"):
            continue
        for marker in ("contents: read", "issues: write", "workflow_dispatch:", "REPO: ${{ github.repository }}", "repos/${REPO}/issues/", "/comments"):
            if marker not in body:
                raise SystemExit(f"{name}: owned issue stress lane missing invariant: {marker}")
        if "schedule:" in body or "pull_request:" in body:
            raise SystemExit(f"{name}: issue stress lane must not be scheduled/PR-triggered")
        if "push:" in body:
            quoted = f'".github/workflows/{name}"' in body or f"'.github/workflows/{name}'" in body
            if not quoted:
                raise SystemExit(f"{name}: push trigger must be scoped to itself")
        count = _stress_write_count(body)
        if count is None or count > MAX_OWNED_STRESS_WRITES:
            raise SystemExit(f"{name}: issue stress loop must be explicit and <= {MAX_OWNED_STRESS_WRITES}")
        if re.search(r"repos/[^$][^\s\"']*/issues/", body):
            raise SystemExit(f"{name}: issue stress target must be github.repository")
        lanes.add(name)
    return lanes


def validate_public_web_write_probe() -> str:
    name = "public-web-write-probe-20260830.yml"
    body = require(name, (
        "contents: write", "workflow_dispatch:", "push:", "paths:",
        "'.github/workflows/public-web-write-probe-20260830.yml'",
        "path='baton/public/the-world-autonomy-note.html'",
        "Public note already exists; no second write.",
        'gh api "repos/${GITHUB_REPOSITORY}/contents/${path}?ref=${branch}"',
        'gh api -X PUT "repos/${GITHUB_REPOSITORY}/contents/${path}"',
        '-f branch="$branch"',
    ), (
        "schedule:", "pull_request:", "id-token: write", "actions: write", "issues: write", "pull-requests: write",
        "packages: write", "deployments: write", "pages: write", "copilot-requests: write", "git push ", "gh pr create",
    ))
    if writes(body) != {"contents"}:
        raise SystemExit(f"{name}: public probe write set drifted: {sorted(writes(body))}")
    if body.count("gh api -X PUT") != 1:
        raise SystemExit(f"{name}: public probe must contain exactly one bounded content write")
    if body.count("baton/public/the-world-autonomy-note.html") != 1:
        raise SystemExit(f"{name}: public probe target must remain exactly one fixed path")
    if ("$" + "{{" + " secrets.") in body:
        raise SystemExit(f"{name}: public probe must use only ephemeral github.token")
    return name


def validate_explicit_lanes() -> set[str]:
    expected = {
        "senju-autonomous-improver.yml": {"contents"},
        "tomoki-forge.yml": {"contents", "pull-requests", "copilot-requests"},
        "tomoki-manager.yml": {"actions", "copilot-requests"},
        "tomoki-hound.yml": {"copilot-requests"},
        "tomoki-skeptic.yml": {"copilot-requests"},
        "ai-factory-boss.yml": {"actions"},
        "the-world-realtime-kernel.yml": {"actions"},
        "the-core-autonomous-director.yml": {"actions", "copilot-requests"},
        "the-world-agent-factory.yml": {"contents", "pull-requests", "copilot-requests"},
        "standment-security-portfolio-rnd.yml": {"contents"},
        "standment-whitehat-portfolio-cycle.yml": {"contents"},
        "jules-backlog-dispatch.yml": {"issues"},
        "jules-issue-router.yml": {"issues"},
        "auto-update-branches.yml": {"contents", "pull-requests"},
        "auto-merge.yml": {"contents", "pull-requests"},
        "the-world-external-write-router.yml": {"issues"},
    }
    # Autonomous/scheduled lanes require full scheduling invariants
    autonomous = {
        "senju-autonomous-improver.yml", "tomoki-forge.yml", "tomoki-manager.yml",
        "tomoki-hound.yml", "tomoki-skeptic.yml", "ai-factory-boss.yml",
        "the-world-realtime-kernel.yml", "the-core-autonomous-director.yml",
        "the-world-agent-factory.yml", "standment-security-portfolio-rnd.yml",
        "standment-whitehat-portfolio-cycle.yml", "the-world-external-write-router.yml",
    }
    for name, want in expected.items():
        markers = ("workflow_dispatch:", "schedule:", "persist-credentials: false") if name in autonomous else ("workflow_dispatch:",)
        body = require(name, markers)
        got = writes(body)
        if got != want:
            raise SystemExit(f"{name}: write set drifted: expected={sorted(want)} actual={sorted(got)}")
    senju = WORKFLOWS["senju-autonomous-improver.yml"]
    for marker in ("senju/state/champion.json", "senju/state/strategy.json", "senju/state/last-evolution-summary.json", "senju/state/last-evolution-plan.md", "CURRENT_BASE_SHA=", "force=false"):
        if marker not in senju:
            raise SystemExit(f"senju-autonomous-improver.yml: missing invariant: {marker}")
    allowed = {"senju/state/champion.json", "senju/state/strategy.json", "senju/state/last-evolution-summary.json", "senju/state/last-evolution-plan.md"}
    observed = {line.strip().split()[-1] for line in senju.splitlines() if line.strip().startswith("put_file ")}
    if observed != allowed:
        raise SystemExit(f"Senju autonomous write allowlist mismatch: {sorted(observed)}")
    forge = WORKFLOWS["tomoki-forge.yml"]
    for marker in ("python /tmp/tomoki-policy-gate.py", "bash /tmp/tomoki-verify.sh", "git add -A -- sales-command-30", "gh pr create"):
        if marker not in forge:
            raise SystemExit(f"tomoki-forge.yml: missing bounded-writer invariant: {marker}")
    director = WORKFLOWS["the-core-autonomous-director.yml"]
    director_cmd = [x.strip() for x in director.splitlines() if x.strip().startswith("copilot -p ")]
    if len(director_cmd) != 1 or "--allow-tool=write" not in director_cmd[0] or "shell(" in director_cmd[0]:
        raise SystemExit("THE CORE Director Copilot permissions drifted")
    for name in ("tomoki-hound.yml", "tomoki-skeptic.yml"):
        body = WORKFLOWS[name]
        cmd = [x.strip() for x in body.splitlines() if x.strip().startswith("copilot -p ")]
        if len(cmd) != 1 or "--allow-tool=write" not in cmd[0] or "shell(" in cmd[0]:
            raise SystemExit(f"{name}: auditor write/shell capability drifted")
        if "continue-on-error: true" in body or "|| true" in cmd[0]:
            raise SystemExit(f"{name}: auditor failures must not be hidden")

    factory = WORKFLOWS["the-world-agent-factory.yml"]
    for marker in (
        "automation/agent_factory/policy.py",
        "--deny-tool=shell",
        "--deny-tool=url",
        "Revert champion if policy rejects it",
        "Validate champion against existing AI and Security R&D systems",
    ):
        if marker not in factory:
            raise SystemExit(f"the-world-agent-factory.yml: missing bounded-factory invariant: {marker}")

    portfolio = WORKFLOWS["standment-security-portfolio-rnd.yml"]
    for marker in (
        "automation/security/portfolio_autobuilder.py",
        "value-lab/senju_bridge.py",
        "verification_claimed",
        "Materialize one portfolio improvement",
    ):
        if marker not in portfolio:
            raise SystemExit(f"standment-security-portfolio-rnd.yml: missing portfolio invariant: {marker}")

    whitehat = WORKFLOWS["standment-whitehat-portfolio-cycle.yml"]
    for marker in (
        "automation/agent_factory/local_worker.py",
        "elite_whitehat",
        "automation/security/whitehat_portfolio_bridge.py",
        "standment-security/whitehat-candidates",
    ):
        if marker not in whitehat:
            raise SystemExit(f"standment-whitehat-portfolio-cycle.yml: missing white-hat invariant: {marker}")
    if "pull_request:" in whitehat or "issues: write" in whitehat or "id-token: write" in whitehat:
        raise SystemExit("standment-whitehat-portfolio-cycle.yml: white-hat lane authority expanded")

    return set(expected)


def validate_unknown_writes(known: set[str]) -> None:
    unknown = {name: sorted(writes(body)) for name, body in WORKFLOWS.items() if writes(body) and name not in known}
    if unknown:
        raise SystemExit(f"Unclassified privileged workflows: {unknown}")


def main() -> int:
    validate_global_safety()
    validate_gateway_client()
    pages = validate_pages_lanes()
    task_worker = validate_task_worker()
    reality = validate_reality_lane()
    research = validate_research_oidc_lane()
    public_probe = validate_public_web_write_probe()
    experiments = validate_experiment_oidc_lanes(pages, {task_worker, reality, research})
    stress = validate_owned_issue_stress_lanes()
    explicit = validate_explicit_lanes()
    known = explicit | pages | experiments | stress | {task_worker, reality, research, public_probe, "security-guard.yml"}
    validate_unknown_writes(known)
    print(json.dumps({
        "status": "PASS", "workflows": len(WORKFLOWS), "pages_lanes": sorted(pages),
        "experiment_oidc_lanes": sorted(experiments), "research_lane": research,
        "public_web_probe": public_probe, "owned_issue_stress_lanes": sorted(stress),
        "reality_lane": reality, "privileged_lanes": sorted(known - {"security-guard.yml"}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
