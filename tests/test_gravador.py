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


_ARECORD = "**** List of CAPTURE Hardware Devices ****\ncard 1: Intelbras [Intelbras USB], device 0: USB Audio [USB Audio]\n"


def test_presente_respeita_o_dispositivo():
    assert Gravador("default").presente(_ARECORD)
    assert Gravador("plughw:CARD=Intelbras,DEV=0").presente(_ARECORD)
    assert Gravador("hw:CARD=Intelbras,DEV=0").presente(_ARECORD)
    assert not Gravador("plughw:CARD=Outra,DEV=0").presente(_ARECORD)
    assert Gravador("outro:texto").presente(_ARECORD)
    assert not Gravador("default").presente("**** List of CAPTURE Hardware Devices ****\n")
    assert not Gravador("default").presente(None.__class__)  # lixo: nunca levanta
