from __future__ import annotations

import pytest

from core.reaction_policy import (
    GESTOS,
    RELEASE_ARM,
    ReactionConfigError,
    ReactionPolicy,
    load_reactions,
    validate_steps,
)


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
        ({"gil": {"gesto": "high wave", "passos": [{"fala": "oi"}]}}, "exatamente um"),
        ({"gil": {"gesture": "high wave"}}, "gesture"),
        ({"gil": {"gesto": "high wave", "fala": "oi"}}, "fala"),
        ({"gil": {"gesto": "continencia"}}, "continencia"),
        ({1: {"gesto": "high wave"}}, "1"),
        ({"desconhecido": {"gesto": "high wave"}}, "desconhecido"),  # reagiria a qualquer estranho
    ],
)
def test_invalid_maps_fail_naming_the_problem(raw, trecho):
    with pytest.raises(ReactionConfigError, match=trecho):
        load_reactions(raw)


ROTINA_GIL = [
    {"postura": "sentido"},
    {"fala": "Olá, aspirante a oficial da reserva Gil, sou o Tenente Nichinica"},
    {"postura": "descansar"},
    {"postura": "a_vontade"},
    {"fala": "Bom ver o senhor"},
]


def test_routine_map_returns_the_steps_in_order():
    raw = {"gil": {"passos": ROTINA_GIL}, "marcos": {"gesto": "shake hand"}}
    assert load_reactions(raw) == {"gil": ROTINA_GIL, "marcos": "shake hand"}


def test_routine_with_only_speech_needs_no_a_vontade():
    assert validate_steps("gil", [{"fala": "oi"}]) == [{"fala": "oi"}]


@pytest.mark.parametrize(
    "passos, trecho",
    [
        ([], "não vazia"),
        ("sentido", "não vazia"),
        ([{"postura": "sentido", "fala": "oi"}], "uma chave só"),
        ([{"gesto": "high wave"}], "gesto"),
        ([{"postura": "pular"}], "pular"),
        ([{"fala": "  "}], "vazia"),
        ([{"postura": "sentido"}], "a_vontade"),  # braço ficaria preso no sentido
        ([{"postura": "a_vontade"}, {"postura": "sentido"}], "a_vontade"),
    ],
)
def test_invalid_routines_fail_naming_the_problem(passos, trecho):
    with pytest.raises(ReactionConfigError, match=trecho):
        load_reactions({"gil": {"passos": passos}})


REACOES = {"gil": "high wave", "marcos": "shake hand"}
GIL = [("gil", 0.8)]
MARCOS = [("marcos", 0.8)]


def _policy(person_cooldown_s=60.0):
    return ReactionPolicy(
        REACOES, confirm_frames=3, person_cooldown_s=person_cooldown_s, global_cooldown_s=10.0, absence_s=5.0
    )


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


def test_person_standing_in_front_is_never_greeted_twice():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    assert _feed(p, [GIL] * 600, start=3.0) == [None] * 600  # 10 min parado na frente


def test_repeats_only_after_cooldown_and_leaving():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    assert _feed(p, [[]] * 10, start=3.0) == [None] * 10  # saiu por 10 s (t=3..12)
    assert _feed(p, [GIL] * 49, start=13.0) == [None] * 49  # voltou, mas t=13..61 < 60 s do disparo
    assert p.update(GIL, 62.0) == ("gil", "high wave")


def test_short_recognition_gap_is_not_leaving():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    # Rosto virado por 4 s (< absence_s) a cada 20 s, por 5 min: nunca conta como saída.
    frames = ([GIL] * 16 + [[]] * 4) * 15
    assert _feed(p, frames, start=3.0) == [None] * len(frames)


def test_release_one_person_allows_greeting_again_right_away():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")
    p.release("gil")
    assert p.update(GIL, 3.0) == ("gil", "high wave")  # sequência de frames não zerou: já confirmado


def test_release_all_clears_global_cooldown_too():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")
    p.release()
    assert _feed(p, [MARCOS] * 3, start=3.0)[-1] == ("marcos", "shake hand")  # t=5, antes do global


def test_release_unknown_name_fails():
    with pytest.raises(KeyError, match="ze"):
        _policy().release("ze")


def test_default_is_five_minutes():
    p = ReactionPolicy(REACOES, confirm_frames=1)
    assert p.update(GIL, 0.0) == ("gil", "high wave")
    assert p.update([], 10.0) is None  # saiu
    assert p.update(GIL, 299.0) is None
    assert p.update(GIL, 300.0) == ("gil", "high wave")


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
