#!/usr/bin/env python3
"""Run candidate -> Authorization -> Senju trial -> credential -> mutation -> expansion."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from engine.authority_expansion_runtime import (
    build_authority_expansion_cases,
    execute_approved_authority_expansion_routes,
)
from engine.candidate_authorization_runtime import promote_attested_candidates
from engine.credential_bound_mutation_runtime import ConfiguredCredentialMutationRuntime
from engine.discovery_capability_leases import issue_discovery_capability_leases
from engine.discovery_external_action import run_discovery_external_actions
from engine.discovery_replica_continuity import rebuild_discovery_capability_replicas
from engine.new_host_authorization_runtime import sync_new_host_authorizations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--max-actions", type=int, default=12)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)

    # Candidate intake is intentionally broad. A candidate can receive temporary exact-host
    # Authority without waiting for a dedicated PR when the exact host itself publishes a
    # valid Authorization attestation. Recommendation/discovery alone still does not mint
    # Authority.
    candidate_promotion = promote_attested_candidates(state)

    # Canonical repository authorizations are synchronized too, but they are no longer the
    # only way for a new candidate to become operational in the runtime.
    new_host_authorization = sync_new_host_authorizations(
        state,
        repo_root=args.repo_root,
    )

    lease_before = issue_discovery_capability_leases(state)
    replicas_before = rebuild_discovery_capability_replicas(state)

    credential_runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=args.repo_root,
        actor="META",
    )
    actions = run_discovery_external_actions(
        state,
        repo_root=args.repo_root,
        max_actions=args.max_actions,
        credential_headers_resolver=credential_runtime,
        payload_resolver=credential_runtime.resolve_payload,
    )

    expansion_cases = build_authority_expansion_cases(
        state,
        repo_root=args.repo_root,
    )
    expansion_execution = execute_approved_authority_expansion_routes(
        state,
        repo_root=args.repo_root,
        credential_headers_resolver=credential_runtime,
        payload_resolver=credential_runtime.resolve_payload,
        max_executions=args.max_actions,
    )
    credential_runtime.flush()

    new_host_authorization_after = sync_new_host_authorizations(
        state,
        repo_root=args.repo_root,
    )
    lease_after = issue_discovery_capability_leases(state)
    replicas_after = rebuild_discovery_capability_replicas(state)

    payload = {
        "schema": "meta-discovery-action-continuity-run/v6",
        "generated_at": int(time.time()),
        "closed_loop": [
            "aggressive_candidate_intake",
            "exact_host_attestation_probe",
            "candidate_to_runtime_Authorization",
            "authorized_site_runtime_registration",
            "senju_same_host_trial_profile",
            "canonical_new_host_authorization_sync",
            "same_cycle_new_host_action_queue",
            "same_cycle_new_host_capability_lease",
            "authorization",
            "capability_lease",
            "replication",
            "authority_inheritance",
            "configured_credential_metadata_selection",
            "short_lived_credential_lease",
            "same_or_narrower_credential_lease_inheritance",
            "meta_synthetic_payload",
            "credential_bound_POST_PUT_PATCH",
            "predeclared_same_host_alternate_path",
            "automatic_authority_expansion_case",
            "META_approval_coordination",
            "existing_owner_envelope_fastpath",
            "approved_POST_PUT_PATCH_method_switch",
            "approved_route_switch_execution",
            "persistence",
            "live_authority_rebuild",
            "auto_recovery",
        ],
        "candidate_authorization": {
            "candidate_count": candidate_promotion.get("candidate_count", 0),
            "attempted_count": candidate_promotion.get("attempted_count", 0),
            "promoted_count": candidate_promotion.get("promoted_count", 0),
            "pr_required_before_runtime_authorization": False,
            "exact_host_attestation_required": True,
            "recommendation_alone_is_authority": False,
            "candidate_prs_may_be_partial": True,
        },
        "new_host_authorization": {
            "canonical_explicit_host_count": new_host_authorization["canonical_explicit_host_count"],
            "activated_host_count": new_host_authorization["activated_host_count"],
            "new_profiles_created": new_host_authorization["new_profiles_created"],
            "senju_trial_ready_count": new_host_authorization["senju_trial_ready_count"],
            "review_case_count": new_host_authorization["review_case_count"],
            "post_action_activated_host_count": new_host_authorization_after["activated_host_count"],
            "post_action_senju_trial_ready_count": new_host_authorization_after["senju_trial_ready_count"],
            "single_pr_completion_contract": False,
            "partial_new_host_pr_allowed": True,
            "same_cycle_action_queue": True,
            "same_cycle_capability_lease": True,
            "unknown_host_auto_authorization_without_evidence": False,
            "external_link_inheritance_used": False,
        },
        "lease_before": lease_before,
        "replicas_before": replicas_before,
        "actions": {
            key: actions[key]
            for key in (
                "attempted",
                "transport_attempts",
                "succeeded",
                "failed",
                "denied_before_execution",
                "alternate_path_successes",
                "credential_failover_successes",
            )
        },
        "authority_expansion": {
            "case_count": expansion_cases["case_count"],
            "approved_route_cases": expansion_cases["approved_route_cases"],
            "waiting_cases": expansion_cases["waiting_cases"],
            "executed": expansion_execution["executed"],
            "transport_attempts": expansion_execution["transport_attempts"],
            "succeeded": expansion_execution["succeeded"],
            "failed": expansion_execution["failed"],
            "automatic_case_generation": True,
            "owner_envelope_fastpath": True,
            "approved_method_switch": True,
            "cross_host_expansion": False,
        },
        "credential_runtime": {
            "configured_grant_metadata_only": True,
            "raw_secret_discovery": False,
            "raw_secret_persistence": False,
            "cross_host_credential_inheritance": False,
            "same_or_narrower_credential_lease_inheritance": True,
            "credential_scope_expansion_on_failure": False,
            "reuse_across_approved_same_host_routes": True,
        },
        "lease_after": lease_after,
        "replicas_after": replicas_after,
    }
    destination = Path(args.json_out) if args.json_out else state / "action_continuity_run.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
