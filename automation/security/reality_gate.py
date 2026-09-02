#!/usr/bin/env python3
"""Fail closed when internal activity is presented as independently verified external value."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github' / 'workflows'


def must_contain(text: str, source: str, markers: tuple[str, ...]) -> None:
    for marker in markers:
        if marker not in text:
            raise SystemExit(f'REALITY_GATE_FAIL: {source} missing truth invariant: {marker}')


def validate_external_proof() -> None:
    path = WORKFLOWS / 'external-public-write-once-20260830.yml'
    if not path.exists():
        raise SystemExit('REALITY_GATE_FAIL: external SaaS proof workflow missing')
    body = path.read_text(encoding='utf-8')
    must_contain(body, path.name, (
        'provider: Slack',
        'WORLD-REAL-SAAS-WRITE-',
        'PROVIDER_ACCEPTED_EXTERNAL_WRITE',
        "provider_acknowledgement_verified': True",
        "independent_readback_verified': False",
        "self_hosted_or_appdeploy_targets_count_as_external_proof': False",
        'Independent readback is a separate verification step',
    ))
    if "independent_readback_verified': True" in body:
        raise SystemExit('REALITY_GATE_FAIL: workflow cannot certify its own independent readback')


def validate_gmail_boundary() -> None:
    heartbeat_path = ROOT / 'runtime' / 'nerve' / 'gmail-heartbeat.json'
    health_path = WORKFLOWS / 'gmail-service-health.yml'
    if not heartbeat_path.exists() or not health_path.exists():
        raise SystemExit('REALITY_GATE_FAIL: Gmail evidence or health gate missing')

    data = json.loads(heartbeat_path.read_text(encoding='utf-8'))
    truth = data.get('truth_contract', {})
    safety = data.get('safety', {})
    evidence = data.get('evidence', {})
    if data.get('status') != 'VERIFIED':
        raise SystemExit('REALITY_GATE_FAIL: Gmail execution heartbeat is not VERIFIED')
    if truth.get('connected_product_path_verified') is not True:
        raise SystemExit('REALITY_GATE_FAIL: connected Gmail execution path is unverified')
    if truth.get('search_success_is_not_sorting_success') is not True:
        raise SystemExit('REALITY_GATE_FAIL: Gmail search must not masquerade as sorting success')
    if evidence.get('operation') != 'gmail.search_email_ids':
        raise SystemExit('REALITY_GATE_FAIL: Gmail evidence is not a real connector search operation')
    for key in ('deleted', 'customer_messages_sent', 'ambiguous_mail_archived', 'mailbox_mutations_this_check'):
        if int(safety.get(key, 0) or 0) != 0:
            raise SystemExit(f'REALITY_GATE_FAIL: read-only Gmail proof mutated mailbox: {key}')

    health = health_path.read_text(encoding='utf-8')
    must_contain(health, health_path.name, (
        "truth.get('connected_product_path_verified') is not True",
        "truth.get('search_success_is_not_sorting_success') is not True",
        "evidence.get('operation') != 'gmail.search_email_ids'",
        "raw_ts = d.get('checked_at_utc')",
        'Placeholder/bootstrap evidence never passes this gate.',
    ))
    if 'BOOTSTRAP_PLACEHOLDER_EVIDENCE' in health or 'GMAIL_SERVICE_NOT_CONFIGURED' in health:
        raise SystemExit('REALITY_GATE_FAIL: Gmail health gate contains a success bypass for unverified bootstrap evidence')


def validate_quarantine() -> None:
    if (WORKFLOWS / 'the-world-portfolio-forge.yml').exists():
        raise SystemExit('REALITY_GATE_FAIL: quarantined unclassified portfolio forge returned')

    rnd = WORKFLOWS / 'standment-autonomous-rnd.yml'
    if rnd.exists():
        body = rnd.read_text(encoding='utf-8')
        if 'contents: write' in body or 'git push ' in body:
            raise SystemExit('REALITY_GATE_FAIL: Standment R&D regained direct default-branch mutation authority')


def main() -> int:
    validate_external_proof()
    validate_gmail_boundary()
    validate_quarantine()
    print('REALITY_GATE_PASS: external claims remain evidence-bounded')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
