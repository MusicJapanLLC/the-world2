from __future__ import annotations

import random

from senju.agents.base import BlueGenome, RedGenome
from senju.memory import genome_from_dict, seeded_population


def test_red_memory_accepts_future_offense_genes_without_crashing():
    genome = genome_from_dict({
        "kind": "red",
        "focus": {"ssrf": 0.8},
        "skill": 0.7,
        "stealth": 0.6,
        "aggression": 0.9,
        "recon_depth": 0.95,
        "chain_synergy": 0.92,
        "evasion_adapt": 0.91,
        "future_attack_gene": 0.99,
    })
    assert isinstance(genome, RedGenome)
    assert genome.skill == 0.7
    assert genome.focus["ssrf"] == 0.8
    assert not hasattr(genome, "future_attack_gene")
    if hasattr(genome, "recon_depth"):
        assert genome.recon_depth == 0.95


def test_blue_memory_accepts_future_defense_genes_without_crashing():
    genome = genome_from_dict({
        "kind": "blue",
        "harden": {"idor": 0.8},
        "detection": 0.7,
        "patch_speed": 0.6,
        "coverage": 0.9,
        "early_warning": 0.95,
        "adaptive_isolation": 0.92,
        "telemetry_sharing": 0.91,
        "future_defense_gene": 0.99,
    })
    assert isinstance(genome, BlueGenome)
    assert genome.detection == 0.7
    assert not hasattr(genome, "future_defense_gene")
    if hasattr(genome, "early_warning"):
        assert genome.early_warning == 0.95


def test_seeded_population_survives_newer_champion_schema():
    champion = {
        "rating": 1400,
        "resources": 180,
        "generation": 12,
        "genome": {
            "kind": "red",
            "focus": {"auth_bypass": 0.9},
            "skill": 0.75,
            "stealth": 0.7,
            "aggression": 0.8,
            "recon_depth": 0.88,
            "chain_synergy": 0.86,
            "evasion_adapt": 0.84,
            "future_attack_gene": 1.0,
        },
    }
    pop = seeded_population(champion, "red", 5, 0.1, random.Random(7))
    assert pop is not None
    assert len(pop) == 5
    assert all(isinstance(agent.genome, RedGenome) for agent in pop)
    assert pop[0].generation == 13
