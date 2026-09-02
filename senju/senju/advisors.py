"""External AI advisor bridge for Senju's improvement loop.

Senju may ask the configured advisors any question. Advice may be promoted into a
repository implementation request when the Foundry synthesis marks it implementable.
Actual code changes remain behind the existing test/repair/PR lane.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

PERSONAL_AI_UI = "https://standment-personal-ai-core-se1c3z.v2.appdeploy.ai/"
PERSONAL_AI_CHAT = f"{PERSONAL_AI_UI.rstrip('/')}/api/chat"
FOUNDRY_UI = "https://test-git-feat-ai-foundry-forge-v2-musicjapanllc.vercel.app/"
FOUNDRY_CHAT = f"{FOUNDRY_UI.rstrip('/')}/api/foundry"
WORKSPACE = hashlib.sha256(b"senju-ai-advisor-hub-v1").hexdigest()[:32]
DEFAULT_QUESTION = (
    "Review the current Senju system and propose the single highest-leverage "
    "improvement to implement next. Give concrete files, tests, success criteria, "
    "expected signal, and overlap risks."
)


def _post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={"content-type": "application/json", "user-agent": "senju-advisor-hub/v2"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw_bytes = response.read()
        status = int(getattr(response, "status", 200))
    raw = raw_bytes.decode()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("advisor returned a non-object JSON response")
    data["_senju_transport"] = {
        "status": status,
        "response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "endpoint": url,
    }
    return data


def _summary_text(summary: dict[str, Any]) -> str:
    selected = summary.get("selected") if isinstance(summary.get("selected"), dict) else {}
    return json.dumps(
        {
            "accepted_strategy_change": summary.get("accepted_strategy_change"),
            "changes": summary.get("changes"),
            "score": selected.get("score"),
            "balance": selected.get("balance"),
            "learning_signal": selected.get("learning_signal"),
            "rating_gain": selected.get("rating_gain"),
            "safe": selected.get("safe"),
            "code_suggestions": summary.get("code_suggestions"),
        },
        ensure_ascii=False,
        indent=2,
    )


def personal_prompt(summary: dict[str, Any], question: str = "") -> str:
    actual_question = (question or DEFAULT_QUESTION).strip()[:16000]
    return f"""You are an always-available senior advisor to the Senju team.

STANDING OWNER RULES:
- Senju may ask you ANY question. Do not narrow the permitted topic domain.
- Answer the question directly, even when it is not about the current simulator.
- Your answer may be used as an implementation proposal when it contains a useful
  repository or owner-controlled development improvement.
- If implementation is relevant, be concrete: files/components, acceptance tests,
  success criteria, expected signal, and overlap/conflict risk.
- Do not claim that code, deployments, tests, or external actions already happened
  unless direct execution evidence proves it.

QUESTION:
{actual_question}

CURRENT SENJU EVALUATION (context, not a restriction on the question):
{_summary_text(summary)}
"""


def ask_personal_ai(summary: dict[str, Any], question: str = "") -> dict[str, Any]:
    data = _post_json(
        PERSONAL_AI_CHAT,
        {"workspace": WORKSPACE, "message": personal_prompt(summary, question)},
        timeout=120,
    )
    answer = str(data.get("answer") or "").strip()
    if not answer:
        raise RuntimeError("Personal AI Core returned no answer")
    return {
        "ok": True,
        "answer": answer[:20000],
        "run_id": str(data.get("runId") or ""),
        "session_id": str(data.get("sessionId") or ""),
        "transport": data.get("_senju_transport") or {},
    }


def _extract_json(text: str) -> dict[str, Any]:
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
    clean = re.sub(r"\s*```$", "", clean)
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Foundry response did not contain JSON")
    data = json.loads(clean[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("Foundry decision was not a JSON object")
    return data


def ask_foundry(
    summary: dict[str, Any],
    personal_answer: str,
    question: str = "",
) -> dict[str, Any]:
    actual_question = (question or DEFAULT_QUESTION).strip()[:16000]
    instruction = """SENJU ADVISOR SYNTHESIS
You are AI FOUNDRY acting as Senju's implementation-oriented engineering peer.
Senju may ask you ANY question; do not narrow the question domain.

For the current question, synthesize your own judgment with the Personal AI Core answer.
Return ONLY strict JSON with keys:
- implement (boolean)
- request (string)
- rationale (string)
- priority (low|medium|high)
- tests (array of strings)
- risks (array of strings)

`implement=true` means only that a concrete, testable improvement should enter the
existing repository implementation lane. It is not a claim that execution already
happened. When the answer is informational/non-implementation-oriented, set
implement=false and still answer the substance briefly in rationale.
Do not claim tests/deployment/external effects without evidence. Prefer one focused,
reviewable change and identify overlap with active work when relevant.
"""
    user = (
        instruction
        + "\nQUESTION:\n"
        + actual_question
        + "\n\nCURRENT SENJU EVALUATION (context only):\n"
        + _summary_text(summary)
        + "\n\nPERSONAL AI CORE ANSWER:\n"
        + (personal_answer or "(advisor unavailable; use your own judgment)")[:20000]
    )
    response = _post_json(
        FOUNDRY_CHAT,
        {"action": "chat", "messages": [{"role": "user", "content": user}]},
        timeout=180,
    )
    decision = _extract_json(str(response.get("text") or ""))
    decision["implement"] = bool(decision.get("implement"))
    decision["request"] = str(decision.get("request") or "")[:12000]
    decision["rationale"] = str(decision.get("rationale") or "")[:4000]
    priority = str(decision.get("priority") or "medium").lower()
    decision["priority"] = priority if priority in {"low", "medium", "high"} else "medium"
    decision["tests"] = [str(x)[:500] for x in (decision.get("tests") or []) if isinstance(x, str)][:8]
    decision["risks"] = [str(x)[:500] for x in (decision.get("risks") or []) if isinstance(x, str)][:8]
    decision["transport"] = response.get("_senju_transport") or {}
    if decision["implement"] and not decision["request"].strip():
        decision["implement"] = False
        decision["rationale"] = "Foundry marked implementation but supplied no request."
    return decision


def foundry_payload(decision: dict[str, Any], run_id: str) -> dict[str, Any]:
    request = str(decision.get("request") or "").strip()
    implementation_request = (
        "Implement this Senju advisor-selected improvement as one focused, reviewable patch. "
        "Use the repository's current state as the source of truth; detect overlap/staleness "
        "before editing. Keep the change inside the authority already available to this "
        "engineering lane. Add/update focused tests, run verification, preserve unrelated "
        "behavior, and do not claim success without evidence.\n\n"
        + request
    )
    return {"job": {"id": run_id, "request": {"request_text": implementation_request}}}


def run(
    summary_path: str,
    out_path: str,
    payload_path: str,
    question: str = "",
) -> dict[str, Any]:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    actual_question = (question or DEFAULT_QUESTION).strip()[:16000]
    personal: dict[str, Any]
    try:
        personal = ask_personal_ai(summary, actual_question)
    except Exception as exc:
        personal = {"ok": False, "answer": "", "error": f"{type(exc).__name__}: {exc}"[:2000]}

    try:
        decision = ask_foundry(summary, str(personal.get("answer") or ""), actual_question)
        foundry_error = ""
    except Exception as exc:
        decision = {
            "implement": False,
            "request": "",
            "rationale": "Foundry synthesis unavailable; no automatic implementation promoted.",
            "priority": "low",
            "tests": [],
            "risks": [],
            "transport": {},
        }
        foundry_error = f"{type(exc).__name__}: {exc}"[:2000]

    run_id = "senju-advisor-" + hashlib.sha256(
        (actual_question + json.dumps(summary, sort_keys=True, default=str)).encode()
    ).hexdigest()[:12]
    result = {
        "schema": "senju-ai-advisor-hub/v2",
        "question": actual_question,
        "rules": {
            "questions": "any_topic_allowed",
            "answers": "may_be_used_for_implementation",
            "raw_answer_direct_execution": False,
            "implementation_requires_existing_engineering_lane": True,
            "evidence_required_before_success_claim": True,
        },
        "sources": {
            "personal_ai_core": PERSONAL_AI_UI,
            "ai_foundry": FOUNDRY_UI,
        },
        "personal_ai": personal,
        "decision": decision,
        "foundry_error": foundry_error,
        "implementation_lane": "AI Foundry Repo Engineer -> sandbox tests/repair -> pull request",
        "run_id": run_id,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = foundry_payload(decision, run_id) if decision.get("implement") else {"job": {}}
    target = Path(payload_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Ask Senju's Personal AI Core + AI Foundry advisors")
    p.add_argument("--summary", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--payload-out", required=True)
    p.add_argument(
        "--question",
        default="",
        help="Any question for the advisor pair. Empty uses the default Senju improvement question.",
    )
    args = p.parse_args()
    result = run(args.summary, args.out, args.payload_out, question=args.question)
    print(
        json.dumps(
            {
                "question": result["question"],
                "implement": result["decision"]["implement"],
                "priority": result["decision"]["priority"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
