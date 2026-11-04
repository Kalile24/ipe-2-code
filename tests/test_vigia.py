from core.vigia import CARENCIA_S, PRIMEIRO_QUADRO_S, SEM_QUADROS_S, decidir


def test_frames_flowing_do_nothing():
    assert decidir(agora=100.0, inicio=0.0, ultimo_quadro=99.9, reiniciou_em=None, reconectou=False) is None


def test_restarts_after_two_seconds_without_frames():
    assert decidir(100.0, 0.0, 100.0 - SEM_QUADROS_S, None, False).startswith("sem quadros")
    assert decidir(100.0, 0.0, 100.0 - SEM_QUADROS_S + 0.3, None, False) is None


def test_reconnection_restarts_at_once_even_during_the_grace_period():
    assert decidir(100.0, 0.0, 99.9, reiniciou_em=99.0, reconectou=True) == "a webcam reconectou"


def test_first_frame_never_arrives():
    assert decidir(PRIMEIRO_QUADRO_S - 1, 0.0, None, None, False) is None
    assert decidir(PRIMEIRO_QUADRO_S, 0.0, None, None, False).startswith("nenhum quadro")


def test_after_a_restart_waits_the_grace_then_tries_again_if_still_no_frame():
    # reiniciou em 50; o último quadro é de antes (40): espera a carência e tenta de novo
    assert decidir(50.0 + CARENCIA_S - 0.5, 0.0, 40.0, 50.0, False) is None
    assert decidir(50.0 + CARENCIA_S, 0.0, 40.0, 50.0, False).startswith("nenhum quadro")


def test_while_no_frame_ever_came_it_does_not_restart_every_grace_period():
    # Subida: o reconhecimento ainda carrega o modelo. Reiniciou em 30 (sem nunca ver quadro):
    # o próximo reinício só 30 s depois, não a cada 6 s.
    assert decidir(30.0 + CARENCIA_S + 1, 0.0, None, 30.0, False) is None
    assert decidir(30.0 + PRIMEIRO_QUADRO_S, 0.0, None, 30.0, False).startswith("nenhum quadro")


def test_after_a_restart_frames_came_back():
    assert decidir(60.0, 0.0, 59.9, 50.0, False) is None
