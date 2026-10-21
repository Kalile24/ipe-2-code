from __future__ import annotations

import pytest

from core.reaction_policy import GESTOS, RELEASE_ARM, ReactionConfigError, ReactionPolicy, load_reactions


def test_gesture_ids_match_the_sdk_action_map():
    assert GESTOS["high wave"] == 26
    assert GESTOS["shake hand"] == 27
    assert GESTOS[RELEASE_ARM] == 99


def test_valid_map_returns_name_to_gesture():
    raw = {"gil": {"gesto": "high wave"}, "marcos": {"gesto": "shake hand"}}
    assert load_reactions(raw) == {"gil": "high wave", "marcos": "shake hand"}


@pytest.mark.parametrize(
    "raw, trecho",
    [
        (None, "mapa"),  # arquivo YAML vazio
        (["gil"], "mapa"),
        ({}, "nenhuma pessoa"),
        ({"gil": "high wave"}, "gil"),
        ({"gil": {}}, "gesto"),
        ({"gil": {"gesture": "high wave"}}, "gesture"),
        ({"gil": {"gesto": "high wave", "fala": "oi"}}, "fala"),
        ({"gil": {"gesto": "continencia"}}, "continencia"),
        ({1: {"gesto": "high wave"}}, "1"),
    ],
)
def test_invalid_maps_fail_naming_the_problem(raw, trecho):
    with pytest.raises(ReactionConfigError, match=trecho):
        load_reactions(raw)


REACOES = {"gil": "high wave", "marcos": "shake hand"}
GIL = [("gil", 0.8)]
MARCOS = [("marcos", 0.8)]


def _policy():
    return ReactionPolicy(REACOES, confirm_frames=3, person_cooldown_s=60.0, global_cooldown_s=10.0)


def _feed(policy, frames, start=0.0):
    """Um frame por segundo a partir de `start` (tempos inteiros: sem erro de ponto flutuante)."""
    return [policy.update(seen, start + i) for i, seen in enumerate(frames)]


def test_fires_only_after_n_consecutive_frames():
    assert _feed(_policy(), [GIL] * 3) == [None, None, ("gil", "high wave")]


def test_a_frame_without_the_person_resets_the_count():
    assert _feed(_policy(), [GIL, GIL, [], GIL, GIL]) == [None] * 5


def test_unknown_and_unmapped_people_never_fire():
    assert _feed(_policy(), [[("desconhecido", 0.3), ("ze_batista", 0.9)]] * 10) == [None] * 10


def test_same_person_twice_in_one_frame_counts_once():
    assert _feed(_policy(), [[("gil", 0.6), ("gil", 0.7)]] * 2) == [None, None]


def test_person_cooldown_blocks_until_it_expires():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    assert p.update(GIL, 61.0) is None  # ainda na frente, dentro dos 60 s
    assert p.update(GIL, 62.0) == ("gil", "high wave")


def test_global_cooldown_blocks_another_person():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    assert _feed(p, [MARCOS] * 4, start=3.0) == [None] * 4  # confirmado em t=5, mas global até t=12
    assert p.update(MARCOS, 12.0) == ("marcos", "shake hand")


def test_two_confirmed_in_same_frame_highest_score_wins_and_other_waits():
    p = _policy()
    ambos = [("gil", 0.6), ("marcos", 0.9)]
    assert _feed(p, [ambos] * 3) == [None, None, ("marcos", "shake hand")]
    assert p.update(ambos, 12.0) == ("gil", "high wave")


def test_confirm_frames_must_be_positive():
    with pytest.raises(ValueError):
        ReactionPolicy(REACOES, confirm_frames=0)
