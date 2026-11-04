from core.remote_combos import AGORA, AUTOMATICO, DOWN, F2, INICIAR, LEFT, PADRAO, PARAR, RIGHT, UP, Combos, botoes


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
