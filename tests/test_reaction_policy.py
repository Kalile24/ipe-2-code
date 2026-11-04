from __future__ import annotations

import pytest

from core.reaction_policy import (
    ReactionConfigError,
    ReactionPolicy,
    load_reactions,
    validate_steps,
)


@pytest.mark.parametrize(
    "raw, trecho",
    [
        (None, "mapa"),  # arquivo YAML vazio
        (["gil"], "mapa"),
        ({}, "nenhuma pessoa"),
        ({"gil": [{"fala": "oi"}]}, "passos"),
        ({"gil": {}}, "passos"),
        ({"gil": {"gesto": "high wave"}}, "gesto"),  # gestos do firmware saíram em 2026-11-04
        ({"gil": {"passos": [{"fala": "oi"}], "fala": "oi"}}, "fala"),
        ({1: {"passos": [{"fala": "oi"}]}}, "1"),
        ({"desconhecido": {"passos": [{"fala": "oi"}]}}, "desconhecido"),  # reagiria a qualquer estranho
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
    raw = {"gil": {"passos": ROTINA_GIL}, "marcos": {"passos": [{"fala": "oi"}]}}
    assert load_reactions(raw) == {"gil": ROTINA_GIL, "marcos": [{"fala": "oi"}]}


def test_pause_step_accepts_seconds():
    assert validate_steps("gil", [{"pausa": 15}, {"pausa": 0.5}]) == [{"pausa": 15}, {"pausa": 0.5}]


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
        ([{"pausa": 0}], "pausa"),
        ([{"pausa": -3}], "pausa"),
        ([{"pausa": 500}], "pausa"),
        ([{"pausa": "15"}], "pausa"),
        ([{"pausa": True}], "pausa"),
        ([{"postura": "sentido"}], "a_vontade"),  # braço ficaria preso no sentido
        ([{"postura": "a_vontade"}, {"postura": "sentido"}], "a_vontade"),
    ],
)
def test_invalid_routines_fail_naming_the_problem(passos, trecho):
    with pytest.raises(ReactionConfigError, match=trecho):
        load_reactions({"gil": {"passos": passos}})


REACOES = {"gil": "rotina gil", "marcos": "rotina marcos"}
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
    assert _feed(_policy(), [GIL] * 3) == [None, None, ("gil", "rotina gil")]


def test_a_frame_without_the_person_resets_the_count():
    assert _feed(_policy(), [GIL, GIL, [], GIL, GIL]) == [None] * 5


def test_a_short_recognition_flicker_keeps_the_count():
    # 10 frames/s: um "desconhecido" de 0,1 s no meio não zera (no robô, de longe, alternava).
    p = _policy()
    tempos = [0.0, 0.1, 0.2, 0.3]
    vistos = [GIL, [("desconhecido", 0.4)], GIL, GIL]
    assert [p.update(v, t) for v, t in zip(vistos, tempos)] == [None, None, None, ("gil", "rotina gil")]


def test_unknown_and_unmapped_people_never_fire():
    assert _feed(_policy(), [[("desconhecido", 0.3), ("ze_batista", 0.9)]] * 10) == [None] * 10


def test_same_person_twice_in_one_frame_counts_once():
    assert _feed(_policy(), [[("gil", 0.6), ("gil", 0.7)]] * 2) == [None, None]


def test_person_standing_in_front_is_never_greeted_twice():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2
    assert _feed(p, [GIL] * 600, start=3.0) == [None] * 600  # 10 min parado na frente


def test_repeats_only_after_cooldown_and_leaving():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2
    assert _feed(p, [[]] * 10, start=3.0) == [None] * 10  # saiu por 10 s (t=3..12)
    assert _feed(p, [GIL] * 49, start=13.0) == [None] * 49  # voltou, mas t=13..61 < 60 s do disparo
    assert p.update(GIL, 62.0) == ("gil", "rotina gil")


def test_short_recognition_gap_is_not_leaving():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2
    # Rosto virado por 4 s (< absence_s) a cada 20 s, por 5 min: nunca conta como saída.
    frames = ([GIL] * 16 + [[]] * 4) * 15
    assert _feed(p, frames, start=3.0) == [None] * len(frames)


def test_release_one_person_allows_greeting_again_right_away():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")
    p.release("gil")
    assert p.update(GIL, 3.0) == ("gil", "rotina gil")  # sequência de frames não zerou: já confirmado


def test_release_all_clears_global_cooldown_too():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")
    p.release()
    assert _feed(p, [MARCOS] * 3, start=3.0)[-1] == ("marcos", "rotina marcos")  # t=5, antes do global


def test_forget_lets_the_person_be_greeted_after_the_global_cooldown():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2; ninguém executou
    p.forget("gil")
    assert _feed(p, [GIL] * 9, start=3.0) == [None] * 9  # t=3..11: cooldown global de 10 s
    assert p.update(GIL, 12.0) == ("gil", "rotina gil")  # sem sair da frente nem esperar 60 s


def test_after_giving_up_it_waits_before_trying_the_same_person_again():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2
    p.desistiu("gil", agora=32.0)  # a aproximação esgotou os 30 s, com o gil ainda na frente
    assert p.update(GIL, 33.0) is None
    assert p.update(GIL, 91.0) is None  # espera padrão: 60 s
    assert p.update(GIL, 92.0) == ("gil", "rotina gil")


def test_giving_up_on_one_person_does_not_block_another():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")
    p.desistiu("gil", agora=32.0)
    assert _feed(p, [MARCOS] * 3, start=33.0)[-1] == ("marcos", "rotina marcos")


def test_release_clears_the_wait_after_giving_up():
    p = _policy()
    _feed(p, [GIL] * 3)
    p.desistiu("gil", agora=32.0)
    p.release()
    assert p.update(GIL, 33.0) == ("gil", "rotina gil")


def test_no_fire_while_a_routine_runs_but_presence_is_tracked():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2
    for t in range(3, 70):  # gil sai; marcos fica na frente enquanto a rotina do gil roda
        assert p.update(MARCOS, float(t), allow_fire=False) is None
    assert p.update(MARCOS, 70.0) == ("marcos", "rotina marcos")  # já confirmado: dispara na hora
    # gil voltou: saiu da frente e passou o cooldown; precisa de 3 frames de novo (t=140..142)
    assert _feed(p, [GIL] * 3, start=140.0) == [None, None, ("gil", "rotina gil")]


def test_release_unknown_name_fails():
    with pytest.raises(KeyError, match="ze"):
        _policy().release("ze")


def test_default_is_five_minutes():
    p = ReactionPolicy(REACOES, confirm_frames=1)
    assert p.update(GIL, 0.0) == ("gil", "rotina gil")
    assert p.update([], 10.0) is None  # saiu
    assert p.update(GIL, 299.0) is None
    assert p.update(GIL, 300.0) == ("gil", "rotina gil")


def test_global_cooldown_blocks_another_person():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")  # disparo em t=2
    assert _feed(p, [MARCOS] * 4, start=3.0) == [None] * 4  # confirmado em t=5, mas global até t=12
    assert p.update(MARCOS, 12.0) == ("marcos", "rotina marcos")


def test_two_confirmed_in_same_frame_highest_score_wins_and_other_waits():
    p = _policy()
    ambos = [("gil", 0.6), ("marcos", 0.9)]
    assert _feed(p, [ambos] * 3) == [None, None, ("marcos", "rotina marcos")]
    assert p.update(ambos, 12.0) == ("gil", "rotina gil")


def test_confirm_frames_must_be_positive():
    with pytest.raises(ValueError):
        ReactionPolicy(REACOES, confirm_frames=0)


def test_now_greets_the_best_mapped_person_ignoring_cooldowns():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "rotina gil")
    assert p.now([("desconhecido", 0.9), ("gil", 0.5), ("marcos", 0.7)], 3.0) == ("marcos", "rotina marcos")
    assert p.now(GIL, 4.0) == ("gil", "rotina gil")  # mesmo dentro dos 5 min


def test_now_with_nobody_mapped_returns_none():
    assert _policy().now([("desconhecido", 0.9)], 0.0) is None
