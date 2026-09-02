from pathlib import Path

from senju.live_guard_adversary import LIVE_LAYERS, _live_surface_checks


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_live_layers_are_the_seven_active_surfaces() -> None:
    assert LIVE_LAYERS == (
        "scopeguard",
        "offense-first",
        "engagement-json",
        "external-contact",
        "security-guard",
        "artifact-guard",
        "autonomy-engine",
    )


def test_live_surface_checks_execute_real_checkout() -> None:
    results = _live_surface_checks(REPO_ROOT)
    assert tuple(result.layer for result in results) == LIVE_LAYERS
    assert all(result.passed for result in results), [
        (result.layer, result.detail) for result in results if not result.passed
    ]
