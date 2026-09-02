from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

MAX_REQUESTS = 12
ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS", "POST"}
SAFE_GRAPHQL_QUERY = "query { __typename }"

@dataclass
class ProbeResult:
    probe: str
    url: str
    status: int | None
    ok: bool
    evidence: dict[str, Any]
    note: str

@dataclass
class Hypothesis:
    severity: str
    title: str
    path: str
    evidence_needed: list[str]
    next_safe_probe: str | None
    remediation: list[str]

def _resolve_host(host: str):
    if host.lower() == "localhost":
        return [ipaddress.ip_address("127.0.0.1")]
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return sorted({ipaddress.ip_address(info[4][0]) for info in infos}, key=str)

def assert_local_target(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https targets are allowed.")
    if not parsed.hostname:
        raise ValueError("Target must include a hostname.")
    if parsed.username or parsed.password:
        raise ValueError("Userinfo in target URL is not allowed.")
    ips = _resolve_host(parsed.hostname)
    if not ips:
        raise ValueError("Target host did not resolve.")
    for ip in ips:
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            raise ValueError(f"Refusing non-local target {parsed.hostname} -> {ip}. This lab is hard-locked to loopback/private/link-local addresses.")
    return parsed

class RequestBudget:
    def __init__(self, maximum: int = MAX_REQUESTS):
        self.maximum = maximum
        self.used = 0
    def spend(self):
        if self.used >= self.maximum:
            raise RuntimeError(f"Request budget exceeded ({self.maximum}).")
        self.used += 1

def request(budget: RequestBudget, method: str, url: str, *, body=None, headers=None, timeout: float = 3.0):
    if method not in ALLOWED_METHODS:
        raise ValueError(f"Method {method} is not permitted.")
    assert_local_target(url)
    budget.spend()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(64 * 1024)
            return ProbeResult(method, url, resp.status, True, {
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "headers": {k.lower(): v for k, v in resp.headers.items()},
                "body_preview": data[:500].decode("utf-8", errors="replace"),
            }, "Read-only / non-destructive probe completed.")
    except urllib.error.HTTPError as exc:
        return ProbeResult(method, url, exc.code, False, {
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "headers": {k.lower(): v for k, v in exc.headers.items()},
            "body_preview": exc.read(4096).decode("utf-8", errors="replace")[:500],
        }, "Endpoint responded with an HTTP error; no bypass attempt was performed.")
    except Exception as exc:
        return ProbeResult(method, url, None, False, {"error": type(exc).__name__, "message": str(exc)}, "Probe failed without retry/fuzzing.")

def finding_text(finding):
    return " ".join(str(v) for v in finding.values() if v is not None).lower()

def plan_hypotheses(findings):
    out = []
    texts = [finding_text(f) for f in findings]
    def has(*terms):
        return any(any(term in text for term in terms) for text in texts)
    if has("graphql", "/graphql"):
        out += [
            Hypothesis("medium", "GraphQL認証・認可境界", "公開GraphQL → 認証境界確認 → resolver/object単位認可不備があれば越権候補", ["401/403境界", "無害queryへの応答", "resolver単位の認可設計"], "graphql_typename", ["resolverごとの認可", "object-level authorization", "depth/complexity/rate limit"]),
            Hypothesis("medium", "GraphQL情報露出", "GraphQL → 詳細エラー/スキーマ露出 → 内部構造推測 → 次段階の攻撃面拡大", ["エラーレスポンス", "本番でのintrospection方針"], "graphql_typename", ["本番エラーの一般化", "不要なschema公開の制限"]),
        ]
    if has("httponly"):
        out.append(Hypothesis("medium", "Cookie属性とXSS連鎖", "XSSが別途成立 → HttpOnly不足CookieがJSから参照可能 → セッション悪用候補", ["Set-Cookie属性", "認証CookieのHttpOnly/Secure/SameSite"], "baseline_headers", ["認証CookieにHttpOnly/Secure/SameSite", "CSP", "出力エスケープ"]))
    if has("serverヘッダー", "server header", "nginx"):
        out.append(Hypothesis("info", "技術フィンガープリント", "Serverヘッダー → 製品推測 → 依存関係/CVE確認の足掛かり", ["Serverヘッダーの詳細度", "実際の依存バージョン"], "baseline_headers", ["詳細バージョンの最小化", "継続的な依存更新"]))
    if has("permissions-policy"):
        out.append(Hypothesis("low", "ブラウザ機能の不要公開面", "Permissions-Policy未設定 → 不要機能の許可範囲が広い → 複合脆弱性時の影響拡大", ["Permissions-Policyレスポンスヘッダー"], "baseline_headers", ["不要機能を明示無効化", "必要最小限のoriginへ限定"]))
    if has("security.txt"):
        out.append(Hypothesis("low", "脆弱性報告経路の欠落", "security.txt不在 → 報告先不明 → 脆弱性修正の遅延", ["/.well-known/security.txt の有無"], "security_txt", ["RFC 9116準拠security.txt設置"]))
    if has("spf", "dmarc"):
        out.append(Hypothesis("medium", "メールなりすまし耐性低下", "SPF/DMARC不備 → ブランド偽装メール → フィッシング/BECの成立率上昇候補", ["DNS上のSPF/DMARC/DKIM設定", "正規送信元一覧"], None, ["SPF/DKIM/DMARC整備", "DMARCをnone→quarantine→rejectへ段階強化"]))
    if has("管理", "admin", "debug"):
        out.append(Hypothesis("medium", "公開管理面", "公開管理面 → 認証強度/公開範囲の確認 → 弱い認証や未修正CVEがあれば管理権限侵害候補", ["外部公開の必要性", "MFA/IP制限/rate limit", "依存バージョン"], None, ["VPN/IP allowlist", "MFA", "rate limit", "不要面の非公開化"]))
    return out

class AutonomousLab:
    def __init__(self, target, findings):
        self.target = target.rstrip("/")
        assert_local_target(self.target)
        self.findings = findings
        self.hypotheses = plan_hypotheses(findings)
        self.results = []
        self.budget = RequestBudget()
    def run_probe(self, name):
        if name == "baseline_headers":
            self.results.append(request(self.budget, "GET", self.target + "/")); return
        if name == "security_txt":
            self.results.append(request(self.budget, "GET", self.target + "/.well-known/security.txt")); return
        if name == "graphql_typename":
            payload = json.dumps({"query": SAFE_GRAPHQL_QUERY}).encode("utf-8")
            self.results.append(request(self.budget, "POST", self.target + "/graphql", body=payload, headers={"Content-Type":"application/json","Accept":"application/json"})); return
        raise ValueError(f"Unknown probe: {name}")
    def run(self):
        planned = []
        for h in self.hypotheses:
            if h.next_safe_probe and h.next_safe_probe not in planned:
                planned.append(h.next_safe_probe)
        if "baseline_headers" not in planned:
            planned.insert(0, "baseline_headers")
        for probe in planned:
            self.run_probe(probe)
        notes = []
        baseline = next((r for r in self.results if r.url == self.target + "/"), None)
        if baseline and isinstance(baseline.evidence.get("headers"), dict):
            headers = baseline.evidence["headers"]
            if headers.get("server"): notes.append(f"Server header exposed: {headers['server']}")
            if not headers.get("permissions-policy"): notes.append("Permissions-Policy header not observed.")
        gql = next((r for r in self.results if r.url.endswith("/graphql")), None)
        if gql:
            if gql.status == 401: notes.append("GraphQL returned 401 to harmless __typename query; authentication boundary is present.")
            elif gql.status == 200: notes.append("GraphQL accepted harmless __typename query; review resolver authorization and schema exposure.")
            elif gql.status: notes.append(f"GraphQL harmless probe returned HTTP {gql.status}.")
        return {"target":self.target,"policy":{"target_scope":"loopback/private/link-local only","max_requests":self.budget.maximum,"requests_used":self.budget.used,"methods":sorted(ALLOWED_METHODS),"forbidden":["credential guessing","authentication bypass attempts","exploit payload execution","destructive mutation","path fuzzing","phishing delivery"]},"hypotheses":[asdict(h) for h in self.hypotheses],"probe_results":[asdict(r) for r in self.results],"analysis":{"notes":notes,"recommended_next_step":"Review hypotheses against source/config and fix the highest-impact confirmed conditions."}}

def render_markdown(report):
    lines = ["# Autonomous Red Team Lab Report","",f"**Target:** `{report['target']}`","",f"**Requests used:** {report['policy']['requests_used']} / {report['policy']['max_requests']}","","## Attack hypotheses",""]
    for i,h in enumerate(report["hypotheses"],1):
        lines += [f"### {i}. [{h['severity'].upper()}] {h['title']}","",f"**経路:** {h['path']}","","**必要証拠:**"]
        lines += [f"- {x}" for x in h["evidence_needed"]]
        lines += ["","**修正:**"] + [f"- {x}" for x in h["remediation"]] + [""]
    lines += ["## Safe probe evidence",""]
    for r in report["probe_results"]:
        lines += [f"### {r['probe']} `{r['url']}`","",f"- Status: {r['status']}",f"- OK: {r['ok']}",f"- Note: {r['note']}",""]
    lines += ["## Automated analysis",""] + [f"- {n}" for n in report["analysis"]["notes"]] + ["",f"**Next:** {report['analysis']['recommended_next_step']}",""]
    return "\n".join(lines)

def load_findings(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    findings = data.get("findings", data if isinstance(data, list) else [])
    if not isinstance(findings, list): raise ValueError("Input must be a list or {'findings': [...]} JSON.")
    return findings

def main():
    p = argparse.ArgumentParser(description="Local-only autonomous defensive red-team lab")
    p.add_argument("--target", required=True)
    p.add_argument("--findings", required=True, type=Path)
    p.add_argument("--out", type=Path, default=Path("redteam-report.md"))
    p.add_argument("--json-out", type=Path, default=Path("redteam-report.json"))
    a = p.parse_args()
    report = AutonomousLab(a.target, load_findings(a.findings)).run()
    a.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    a.out.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {a.out} and {a.json_out}")

if __name__ == "__main__":
    main()
