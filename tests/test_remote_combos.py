import pytest

from core.remote_combos import (
    AGORA, AUTOMATICO, DAMP, DOWN, F2, INICIAR, LEFT, LEVANTAR, PADRAO, PARAR, RIGHT, SEGURAR, UP, A, B, Combos,
    botoes, segue_apertado,
)


def test_damp_and_stand_up_are_f2_with_b_and_a_and_must_be_held():
    c = Combos(PADRAO)
    assert [c.update(k) for k in [F2 | B, 0, F2 | A]] == [DAMP, None, LEVANTAR]
    assert set(SEGURAR) == {DAMP, LEVANTAR}


def test_no_combo_collides_with_the_hhhh_select_f3():
    from core.remote_combos import SELECT
    assert all(not mascara & SELECT for mascara in PADRAO.values())


def test_buttons_come_from_bytes_2_and_3_little_endian():
    assert botoes([0x55, 0x51, 0x80, 0x10] + [0] * 36) == F2 | UP


def test_fires_once_on_the_press_edge_and_again_after_release():
    c = Combos(PADRAO)
    assert [c.update(k) for k in [F2, F2 | UP, F2 | UP, F2, F2 | UP]] == [None, INICIAR, None, None, INICIAR]


def test_each_combo_maps_to_its_action_and_stop_wins():
    c = Combos(PADRAO)
    assert [c.update(k) for k in [F2 | RIGHT, 0, F2 | LEFT, 0, F2 | DOWN | UP]] == [AGORA, None, AUTOMATICO, None, PARAR]


def test_single_buttons_do_nothing():
    c = Combos(PADRAO)
    assert [c.update(k) for k in [UP, 0, F2, 0, DOWN]] == [None] * 5


@pytest.mark.parametrize("keys, recebido_em, agora, esperado", [
    (F2 | B, 10.0, 10.1, True),         # apertado, leitura recente
    (F2 | B | UP, 10.0, 10.1, True),    # outra tecla junto não solta o combo
    (F2, 10.0, 10.1, False),            # soltou o B
    (None, 0.0, 10.1, False),           # nunca chegou leitura
    (F2 | B, 10.0, 10.3, False),        # leituras pararam de chegar: não dá para saber que segue apertado
])
def test_a_held_combo_needs_a_recent_reading(keys, recebido_em, agora, esperado):
    assert segue_apertado(keys, F2 | B, recebido_em, agora) is esperado
