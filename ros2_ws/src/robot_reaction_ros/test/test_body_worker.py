"""Testes do body_worker e do SubprocessBody sem robô: o corpo é um dublê."""
from __future__ import annotations

import io
import json
import sys
import textwrap

import pytest

from robot_reaction_ros.body_node import SubprocessBody
from robot_reaction_ros.body_worker import serve


class _FakeBody:
    def __init__(self, erro_em=None):
        self.calls = []
        self.erro_em = erro_em

    def initialize(self):
        self.calls.append("initialize")
        return True

    def posture(self, nome):
        self.calls.append(nome)
        if nome == self.erro_em:
            raise RuntimeError("SDK caiu")
        return nome != "falha"

    def shutdown(self):
        self.calls.append("shutdown")


def _serve(body, *ordens):
    out = io.StringIO()
    serve(body, io.StringIO("".join(json.dumps(o) + "\n" for o in ordens)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_serve_answers_each_order_and_shuts_down():
    body = _FakeBody()
    respostas = _serve(body, {"cmd": "initialize"}, {"cmd": "posture", "nome": "sentido"}, {"cmd": "shutdown"})
    assert body.calls == ["initialize", "sentido", "shutdown"]
    assert respostas == [{"ok": True}, {"ok": True}, {"ok": True}]


def test_closed_input_also_shuts_down():
    body = _FakeBody()
    assert _serve(body, {"cmd": "initialize"}) == [{"ok": True}, {"ok": True}]
    assert body.calls == ["initialize", "shutdown"]


def test_failures_and_errors_are_answers_not_crashes():
    body = _FakeBody(erro_em="descansar")
    respostas = _serve(
        body,
        {"cmd": "posture", "nome": "falha"},
        {"cmd": "posture", "nome": "descansar"},
        {"cmd": "pular"},
        {"cmd": "posture", "nome": "a_vontade"},
    )
    assert respostas[0] == {"ok": False}
    assert respostas[1]["ok"] is False and "SDK caiu" in respostas[1]["erro"]
    assert respostas[2]["ok"] is False and "pular" in respostas[2]["erro"]
    assert respostas[3] == {"ok": True}


FAKE_WORKER = textwrap.dedent(
    """
    import json, sys
    from robot_reaction_ros.body_worker import serve
    class Body:
        def initialize(self): return True
        def posture(self, nome): return nome != "falha"
        def shutdown(self): print("shutdown", file=sys.stderr)
    print(json.dumps({"ok": True}), flush=True)
    serve(Body(), sys.stdin, sys.stdout)
    """
)


def test_subprocess_body_talks_to_a_real_process():
    body = SubprocessBody("", "", command=[sys.executable, "-c", FAKE_WORKER])
    assert body.initialize() is True
    assert body.posture("sentido") is True
    assert body.posture("falha") is False
    body.shutdown()
    assert body._proc.returncode == 0


def test_worker_that_fails_to_start_raises():
    falha = 'import json; print(json.dumps({"ok": False, "erro": "sem SDK"}), flush=True)'
    with pytest.raises(RuntimeError, match="sem SDK"):
        SubprocessBody("", "", command=[sys.executable, "-c", falha])


def test_dead_worker_makes_postures_fail():
    body = SubprocessBody("", "", command=[sys.executable, "-c", FAKE_WORKER])
    body._proc.kill()
    body._proc.wait()
    assert body.posture("sentido") is False
