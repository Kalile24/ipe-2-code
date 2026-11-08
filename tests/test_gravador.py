from __future__ import annotations

import time

import pytest

from core.gravador import Gravador


def test_gravador_junta_o_stdout():
    g = Gravador("x", comando=["sh", "-c", "printf abc; sleep 5"])
    g.iniciar()
    time.sleep(0.2)
    t = time.monotonic()
    assert g.parar() == b"abc"
    assert time.monotonic() - t < 3


def test_presente_nunca_levanta():
    assert isinstance(Gravador("x").presente(), bool)


def test_processo_que_sai_na_partida_levanta_oserror():
    with pytest.raises(OSError):
        Gravador("x", comando=["sh", "-c", "exit 1"]).iniciar()
