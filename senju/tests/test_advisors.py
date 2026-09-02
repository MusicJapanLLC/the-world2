from __future__ import annotations

from senju import advisors


def test_personal_prompt_allows_any_question_and_is_implementation_oriented() -> None:
    question = "哲学でも営業でもPythonでも自由に答えて"
    prompt = advisors.personal_prompt(
        {
            "accepted_strategy_change": False,
            "selected": {"score": 12.3, "safe": True},
            "code_suggestions": ["improve observability"],
        },
        question,
    )
    assert question in prompt
    assert "ANY question" in prompt
    assert "acceptance tests" in prompt
    assert "CURRENT SENJU EVALUATION" in prompt


def test_requested_foundry_url_is_the_live_chat_endpoint() -> None:
    assert advisors.FOUNDRY_CHAT == (
        "https://test-git-feat-ai-foundry-forge-v2-musicjapanllc.vercel.app/api/foundry"
    )


def test_extract_json_accepts_fenced_payload() -> None:
    decision = advisors._extract_json(
        "```json\n{\"implement\": true, \"request\": \"add test\", \"priority\": \"high\"}\n```"
    )
    assert decision["implement"] is True
    assert decision["request"] == "add test"


def test_foundry_payload_allows_selected_improvement_to_enter_existing_lane() -> None:
    payload = advisors.foundry_payload(
        {"implement": True, "request": "Improve tournament diagnostics."},
        "senju-advisor-test",
    )
    text = payload["job"]["request"]["request_text"]
    assert "authority already available" in text
    assert "detect overlap/staleness" in text
    assert "Improve tournament diagnostics" in text
    assert "do not claim success without evidence" in text


def test_default_question_exists_for_autonomous_daily_use() -> None:
    assert "highest-leverage" in advisors.DEFAULT_QUESTION
