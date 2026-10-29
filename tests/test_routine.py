from __future__ import annotations

from core.routine import run_routine

ROTINA = [
    {"postura": "sentido"},
    {"fala": "Olá, aspirante a oficial da reserva Gil, sou o Tenente Nichinica"},
    {"postura": "descansar"},
    {"postura": "a_vontade"},
    {"fala": "Bom ver o senhor"},
]


class _Robo:
    """Grava a ordem de tudo: posturas, falas e pausas."""

    def __init__(self, falha=None, erro=None, fala_falha=False):
        self.eventos = []
        self.falha = falha
        self.erro = erro
        self.fala_falha = fala_falha

    def postura(self, nome):
        self.eventos.append(("postura", nome))
        if nome == self.erro:
            raise RuntimeError("SDK caiu")
        return nome != self.falha

    def falar(self, texto):
        self.eventos.append(("fala", texto))
        if self.fala_falha:
            raise RuntimeError("sem caixa")

    def sleep(self, s):
        self.eventos.append(("pausa", s))

    def rodar(self, passos=ROTINA, **kw):
        return run_routine(passos, self.postura, self.falar, pausa_s=2.0, log=lambda _: None, sleep=self.sleep, **kw)


def test_runs_in_order_with_a_pause_after_each_posture():
    r = _Robo()
    assert r.rodar() is True
    assert r.eventos == [
        ("postura", "sentido"),
        ("pausa", 2.0),
        ("fala", "Olá, aspirante a oficial da reserva Gil, sou o Tenente Nichinica"),
        ("postura", "descansar"),
        ("pausa", 2.0),
        ("postura", "a_vontade"),
        ("pausa", 2.0),
        ("fala", "Bom ver o senhor"),
    ]


def test_no_pause_after_the_last_step():
    r = _Robo()
    assert r.rodar([{"postura": "a_vontade"}]) is True
    assert r.eventos == [("postura", "a_vontade")]


def test_failed_posture_stops_and_releases_the_arms():
    r = _Robo(falha="descansar")
    assert r.rodar() is False
    assert [e for e in r.eventos if e[0] == "postura"] == [
        ("postura", "sentido"),
        ("postura", "descansar"),
        ("postura", "a_vontade"),
    ]
    assert ("fala", "Bom ver o senhor") not in r.eventos


def test_exception_in_posture_is_a_failure_and_releases_the_arms():
    r = _Robo(erro="sentido")
    assert r.rodar() is False
    assert [e for e in r.eventos if e[0] == "postura"] == [("postura", "sentido"), ("postura", "a_vontade")]


def test_failed_a_vontade_does_not_retry_itself():
    r = _Robo(falha="a_vontade")
    assert r.rodar() is False
    assert [e for e in r.eventos if e == ("postura", "a_vontade")] == [("postura", "a_vontade")]


def test_speech_failure_does_not_stop_the_movement():
    r = _Robo(fala_falha=True)
    assert r.rodar() is True
    assert ("postura", "a_vontade") in r.eventos


def test_stop_request_is_checked_before_each_step():
    r = _Robo()
    feitos = []
    assert r.rodar(deve_parar=lambda: len(feitos) > 0 or feitos.append(1)) is False
    assert r.eventos == [("postura", "sentido"), ("pausa", 2.0)]
