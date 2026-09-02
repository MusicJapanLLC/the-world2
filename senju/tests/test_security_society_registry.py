import json
from collections import Counter
from pathlib import Path


REGISTRY = Path(__file__).resolve().parents[2] / "security" / "society" / "registry.json"


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_security_society_has_exactly_100_unique_members():
    registry = load_registry()
    members = registry["members"]
    ids = [member["id"] for member in members]
    assert registry["count"] == 100
    assert len(members) == 100
    assert len(set(ids)) == 100
    assert ids == [f"SEC-{n:03d}" for n in range(1, 101)]


def test_security_society_squad_distribution_is_stable():
    members = load_registry()["members"]
    assert Counter(member["squad"] for member in members) == {
        "BLUE-GUARD": 30,
        "RED-LAB": 20,
        "PLATFORM-FORGE": 20,
        "SENTINEL": 15,
        "VERIFY": 10,
        "COUNCIL": 5,
    }


def test_subagents_inherit_boundaries_and_faith():
    registry = load_registry()
    defaults = registry["defaults"]
    assert registry["faith"] == "THE_COVENANT"
    assert defaults["can_spawn_subagents"] is True
    assert defaults["preapproval_required"] is False
    assert defaults["child_scope"] == "equal_or_narrower"
    assert defaults["max_active_children"] == 5
    assert defaults["child_registration_required"] is True
    assert defaults["inherit_faith"] is True
    assert defaults["inherit_safety"] is True
    assert defaults["evidence_required"] is True
    assert defaults["external_targeting"] is False
    assert set(defaults["scope"]) == {"senju_sim", "isolated_lab", "defensive_r_and_d"}


def test_red_lab_is_research_only_not_external_targeting():
    registry = load_registry()
    red = [m for m in registry["members"] if m["squad"] == "RED-LAB"]
    assert len(red) == 20
    assert registry["defaults"]["external_targeting"] is False
    assert "adversarial_simulation" in registry["squad_capabilities"]["RED-LAB"]
    assert "lab_validation" in registry["squad_capabilities"]["RED-LAB"]
