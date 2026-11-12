"""Testes do body_worker e do SubprocessBody sem robô: o corpo é um dublê."""
from __future__ import annotations

import io
import json
import os
import sys
import textwrap
import threading
import time

import pytest

from robot_reaction_ros.body_node import SubprocessBody
from robot_reaction_ros.body_worker import G1Body, serve


class _FakeBody:
    def __init__(self, erro_em=None):
        self.calls = []
        self.erro_em = erro_em
        self.solta_lenta = threading.Event()

    def initialize(self, so_equilibrio=False):
        self.calls.append("initialize")
        return True

    def posture(self, nome):
        self.calls.append(nome)
        if nome == "lenta":
            self.solta_lenta.wait(5.0)
        if nome == self.erro_em:
            raise RuntimeError("SDK caiu")
        return nome != "falha"

    def velocity(self, vx, vyaw):
        self.calls.append(("velocidade", vx, vyaw))

    def stop(self):
        self.calls.append("parar")

    def shutdown(self):
        self.calls.append("shutdown")

    def meia_volta(self, cfg, interromper, log):
        self.calls.append(("meia_volta", cfg))
        if cfg.passo_m == 0.42:  # a lenta: espera o `parar`
            interromper.wait(5.0)
            return "interrompida" if interromper.is_set() else ""
        return ""


def _serve(body, *ordens):
    out = io.StringIO()
    serve(body, io.StringIO("".join(json.dumps(o) + "\n" for o in ordens)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_serve_answers_each_order_and_shuts_down():
    body = _FakeBody()
    respostas = _serve(body, {"cmd": "initialize"}, {"cmd": "posture", "nome": "sentido"}, {"cmd": "shutdown"})
    assert "parar" in body.calls  # no encerramento para de andar (a ordem com a fila varia)
    assert [c for c in body.calls if c != "parar"] == ["initialize", "sentido", "shutdown"]
    assert respostas == [{"ok": True}, {"ok": True}, {"ok": True}]


def test_replies_repeat_the_order_id():
    body = _FakeBody()
    respostas = _serve(body, {"id": 7, "cmd": "posture", "nome": "sentido"}, {"id": 8, "cmd": "shutdown"})
    assert respostas == [{"id": 7, "ok": True}, {"id": 8, "ok": True}]


def test_closed_input_also_shuts_down():
    body = _FakeBody()
    assert _serve(body, {"cmd": "initialize"}) == [{"ok": True}, {"ok": True}]
    assert "parar" in body.calls
    assert [c for c in body.calls if c != "parar"] == ["initialize", "shutdown"]


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


def test_velocity_and_stop_are_served_while_a_posture_runs():
    body = _FakeBody()
    r, w = os.pipe()
    inp, entrada = os.fdopen(r), os.fdopen(w, "w")
    out = io.StringIO()
    worker = threading.Thread(target=serve, args=(body, inp, out), daemon=True)
    worker.start()

    def manda(ordem, chamadas):
        entrada.write(json.dumps(ordem) + "\n")
        entrada.flush()
        fim = time.monotonic() + 2.0
        while len(body.calls) < chamadas and time.monotonic() < fim:
            time.sleep(0.01)

    manda({"id": 1, "cmd": "posture", "nome": "lenta"}, 1)  # a executora fica presa nela
    manda({"cmd": "velocidade", "vx": 0.1, "vyaw": -0.2}, 2)
    manda({"cmd": "parar"}, 3)
    assert body.calls[:3] == ["lenta", ("velocidade", 0.1, -0.2), "parar"]  # antes da postura acabar
    body.solta_lenta.set()
    entrada.write(json.dumps({"id": 2, "cmd": "shutdown"}) + "\n")
    entrada.close()
    worker.join(5.0)
    respostas = [json.loads(line) for line in out.getvalue().splitlines()]
    assert respostas == [{"id": 1, "ok": True}, {"id": 2, "ok": True}]  # velocidade/parar não respondem
    assert body.calls[-1] == "shutdown"


FAKE_WORKER = textwrap.dedent(
    """
    import json, sys, time
    from robot_reaction_ros.body_worker import serve
    class Body:
        def initialize(self, so_equilibrio=False): return True
        def velocity(self, vx, vyaw): print("velocidade", vx, vyaw, file=sys.stderr)
        def stop(self): print("parar", file=sys.stderr)
        def posture(self, nome):
            if nome == "lenta":
                time.sleep(1.0)
            return nome != "falha"
        def shutdown(self): print("shutdown", file=sys.stderr)
        def meia_volta(self, cfg, interromper, log):
            return "tempo esgotado" if cfg.passo_m == 0.3 else ""
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


def test_late_reply_is_not_taken_as_the_next_answer():
    body = SubprocessBody("", "", command=[sys.executable, "-c", FAKE_WORKER], posture_timeout_s=0.3)
    assert body.posture("lenta") is False  # desistiu de esperar; a resposta (ok) chega depois
    body._posture_timeout_s = 5.0
    assert body.posture("falha") is False  # a resposta atrasada "ok" não vale para esta ordem
    assert body.posture("sentido") is True
    body.shutdown()
    assert body._proc.returncode == 0


def test_subprocess_body_sends_velocity_without_waiting():
    body = SubprocessBody("", "", command=[sys.executable, "-c", FAKE_WORKER])
    postura = threading.Thread(target=body.posture, args=("lenta",))
    postura.start()
    time.sleep(0.2)  # a postura lenta já está com o lock das chamadas
    inicio = time.monotonic()
    body.velocity(0.1, -0.2)
    body.stop()
    assert time.monotonic() - inicio < 0.1
    postura.join(5.0)
    assert body.initialize(so_equilibrio=True) is True
    body.shutdown()
    assert body._proc.returncode == 0


class _Loco:
    def __init__(self):
        self.calls = []

    def SetVelocity(self, vx, vy, vyaw, duracao):
        self.calls.append(("SetVelocity", vx, vy, vyaw, duracao))

    def StopMove(self):
        self.calls.append("StopMove")


class _FakeController:
    def __init__(self, fsm):
        self.fsm = fsm
        self.initialized_801 = False
        self.inicializou = False
        self.logs = []
        self.loco = _Loco()

    def state(self, label):
        if isinstance(self.fsm, list):  # sequência de leituras: a última se repete
            return self.fsm.pop(0) if len(self.fsm) > 1 else self.fsm[0]
        return self.fsm

    def log(self, text):
        self.logs.append(text)

    def initialize_to_balance(self, permitir_damp=True):
        self.inicializou = True
        self.permitir_damp = permitir_damp
        if not permitir_damp:
            self.initialized_801 = True
        return True


def _g1_body(fsm):
    body = G1Body.__new__(G1Body)  # sem o __init__: ele importaria o SDK da Unitree
    body.robot = _FakeController(fsm)
    body.ESPERA_ESTADO_S = 0.2  # os testes não esperam os 5 s de releitura
    body.INTERVALO_ESTADO_S = 0.01
    return body


def test_balance_only_rereads_a_failed_first_reading():
    # No robô: a 1ª leitura logo depois de conectar falhava (None) e dizia "não estou em equilíbrio".
    body = _g1_body([(None, None), (801, 0)])
    assert body.initialize(so_equilibrio=True) is True
    assert body.robot.permitir_damp is False


def test_balance_801_with_unanswered_mode_is_accepted_without_damp():
    # No robô: FSM_ID=801, FSM_MODE=None (o RPC do MODE não respondeu) → "não estou em equilíbrio".
    body = _g1_body((801, None))
    assert body.initialize(so_equilibrio=True) is True
    assert body.robot.permitir_damp is False


@pytest.mark.parametrize("fsm", [(None, None), (4, None), (1, None)])
def test_balance_only_still_refuses_without_801(fsm):
    body = _g1_body(fsm)
    assert body.initialize(so_equilibrio=True) is False


def test_mode_3_gets_time_to_clear_before_starting():
    # Logo depois de outra rodada soltar os braços o MODE fica em 3 por um tempo.
    body = _g1_body([(801, 3), (801, 0)])
    assert body.initialize(so_equilibrio=True) is True
    assert body.robot.fsm == [(801, 0)]  # releu até o MODE 0


@pytest.mark.parametrize("so_equilibrio", [False, True])
def test_mode_3_that_does_not_clear_still_starts_without_damp(so_equilibrio):
    # Como no último teste físico: em pé no 801, recusar impediria a operação.
    body = _g1_body((801, 3))
    assert body.initialize(so_equilibrio=so_equilibrio) is True
    assert body.robot.permitir_damp is False


@pytest.mark.parametrize("fsm", [(0, 0), (1, 0)])
def test_initialize_from_damp_or_zero_torque_goes_through_damp(fsm):
    body = _g1_body(fsm)
    assert body.initialize() is True
    assert body.robot.inicializou and not body.robot.initialized_801


def test_initialize_already_balanced_skips_the_damp():
    body = _g1_body((801, 0))
    assert body.initialize() is True
    assert body.robot.initialized_801  # o initialize_to_balance só captura a postura


@pytest.mark.parametrize("fsm", [(4, 0), (500, 0), (801, 1), (None, None)])
def test_initialize_refuses_when_standing_otherwise(fsm):
    body = _g1_body(fsm)
    assert body.initialize() is False
    assert not body.robot.inicializou
    assert "derrubaria" in body.robot.logs[-1]


def test_initialize_balance_only_refuses_limp_robot():
    body = _g1_body((1, 0))
    assert body.initialize(so_equilibrio=True) is False
    assert not body.robot.inicializou and "equilíbrio" in body.robot.logs[-1]


def test_initialize_balance_only_accepts_801():
    body = _g1_body((801, 0))
    assert body.initialize(so_equilibrio=True) is True
    assert body.robot.initialized_801


def test_only_one_worker_holds_the_body(tmp_path):
    from robot_reaction_ros.body_worker import travar_corpo

    caminho = str(tmp_path / "trava")
    primeiro = travar_corpo(caminho, espera_s=0.0)
    assert primeiro is not None
    assert travar_corpo(caminho, espera_s=0.6) is None  # o segundo espera e desiste
    primeiro.close()  # o primeiro saiu
    assert travar_corpo(caminho, espera_s=0.0) is not None


@pytest.mark.parametrize("so_equilibrio", [False, True])
def test_standing_robot_never_allows_the_damp(so_equilibrio):
    body = _g1_body((801, 0))
    body.initialize(so_equilibrio=so_equilibrio)
    assert body.robot.permitir_damp is False


@pytest.mark.parametrize("fsm", [(0, 0), (1, 0)])
def test_limp_robot_still_allows_the_damp(fsm):
    body = _g1_body(fsm)
    body.initialize()
    assert body.robot.permitir_damp is True


def test_velocity_and_stop_drive_the_loco_client():
    body = _g1_body((801, 0))
    body.velocity(0.1, -0.2)
    body.stop()
    assert body.robot.loco.calls == [("SetVelocity", 0.1, 0.0, -0.2, 0.5), "StopMove"]


def test_velocity_ceiling_matches_the_panel_limits_and_reaches_the_sdk():
    from core.approach import LIMITES_OPERACAO
    from robot_reaction_ros import body_worker

    assert body_worker.VX_MAX == LIMITES_OPERACAO["vx"][1]
    assert body_worker.VYAW_MAX == LIMITES_OPERACAO["vyaw_max"][1]
    corpo = G1Body.__new__(G1Body)
    corpo.robot = _FakeController(801)
    corpo.velocity(5.0, -5.0)
    corpo.velocity(0.2, 0.3)
    assert corpo.robot.loco.calls == [("SetVelocity", 0.5, 0.0, -0.8, 0.5), ("SetVelocity", 0.2, 0.0, 0.3, 0.5)]


_CFG = {
    "vyaw_meia_volta": 0.5, "tolerancia_meia_volta_graus": 10.0, "passo_m": 0.2,
    "vx_passo": 0.2, "tempo_max_meia_volta_s": 12.0,
}


def test_meia_volta_vai_para_a_executora_e_responde():
    body = _FakeBody()
    respostas = _serve(body, {"id": 1, "cmd": "meia_volta", "cfg": _CFG}, {"id": 2, "cmd": "shutdown"})
    assert respostas == [{"id": 1, "ok": True}, {"id": 2, "ok": True}]
    chamada = [c for c in body.calls if c != "parar"][0]  # o `parar` do shutdown pode vir antes
    assert chamada[0] == "meia_volta" and chamada[1].vx_passo == 0.2


def test_parar_interrompe_meia_volta():
    body = _FakeBody()
    r, w = os.pipe()
    inp, entrada = os.fdopen(r), os.fdopen(w, "w")
    out = io.StringIO()
    worker = threading.Thread(target=serve, args=(body, inp, out), daemon=True)
    worker.start()
    entrada.write(json.dumps({"id": 1, "cmd": "meia_volta", "cfg": {**_CFG, "passo_m": 0.42}}) + "\n")
    entrada.flush()
    while not body.calls:
        time.sleep(0.01)
    t0 = time.monotonic()
    entrada.write(json.dumps({"cmd": "parar"}) + "\n")
    entrada.flush()
    while '"id": 1' not in out.getvalue() and time.monotonic() - t0 < 3.0:
        time.sleep(0.01)
    assert time.monotonic() - t0 < 1.0
    assert "parar" in body.calls
    assert json.loads(out.getvalue().splitlines()[0]) == {"id": 1, "ok": False, "erro": "interrompida"}
    entrada.close()
    worker.join(5.0)


class _FakeLoco:
    def __init__(self, robot):
        self.robot, self.comandos, self.velocidades = robot, [], []

    def SetVelocity(self, vx, vy, vyaw, duracao):
        self.comandos.append("SetVelocity")
        self.velocidades.append((vx, vy, vyaw))
        if self.robot.low_state is not None:
            self.robot.low_state.imu_state.rpy[2] += 0.1

    def StopMove(self):
        self.comandos.append("StopMove")


class _FakeRobotImu:
    def __init__(self, com_estado=True):
        class _Imu:
            rpy = [0.0, 0.0, 0.0]

        class _Estado:
            imu_state = _Imu()

        self.low_state = _Estado() if com_estado else None
        self.loco = _FakeLoco(self)


def _cfg(**kw):
    from core.meia_volta import MeiaVoltaConfig

    return MeiaVoltaConfig(**{**_CFG, **kw})


def test_meia_volta_sem_low_state():
    body = G1Body.__new__(G1Body)
    body.robot = _FakeRobotImu(com_estado=False)
    assert body.meia_volta(_cfg(), threading.Event(), lambda t: None) == "sem angulo"
    assert "SetVelocity" not in body.robot.loco.comandos


def test_g1body_meia_volta_para_ao_chegar():
    body = G1Body.__new__(G1Body)
    body.robot = _FakeRobotImu()
    assert body.meia_volta(_cfg(passo_m=0.0), threading.Event(), lambda t: None) == ""
    assert body.robot.loco.comandos[-1] == "StopMove"
    assert all(vx == 0.0 and vyaw > 0 for vx, _, vyaw in body.robot.loco.velocidades)  # esquerda


def test_g1body_meia_volta_com_passo():
    body = G1Body.__new__(G1Body)
    body.robot = _FakeRobotImu()
    assert body.meia_volta(_cfg(passo_m=0.04), threading.Event(), lambda t: None) == ""
    c = body.robot.loco.comandos
    i = c.index("StopMove")  # fim do giro
    assert set(c[:i]) == {"SetVelocity"} and c[-1] == "StopMove" and i < len(c) - 1
    v = body.robot.loco.velocidades
    assert v[-1] == (0.2, 0.0, 0.0) and all(x[0] == 0.0 for x in v[: i])


def test_g1body_meia_volta_interrompida_no_passo():
    body = G1Body.__new__(G1Body)
    body.robot = _FakeRobotImu()
    interromper = threading.Event()
    orig = body.robot.loco.SetVelocity

    def seta(vx, vy, vyaw, d):
        orig(vx, vy, vyaw, d)
        if vx > 0:
            interromper.set()

    body.robot.loco.SetVelocity = seta
    assert body.meia_volta(_cfg(passo_m=1.0), interromper, lambda t: None) == "interrompida"
    assert body.robot.loco.comandos[-1] == "StopMove"


def _abre(body):
    r, w = os.pipe()
    inp, entrada = os.fdopen(r), os.fdopen(w, "w")
    out = io.StringIO()
    worker = threading.Thread(target=serve, args=(body, inp, out), daemon=True)
    worker.start()
    return entrada, out, worker


def test_entrada_fechada_interrompe_meia_volta():
    body = _FakeBody()
    entrada, out, worker = _abre(body)
    entrada.write(json.dumps({"id": 1, "cmd": "meia_volta", "cfg": {**_CFG, "passo_m": 0.42}}) + "\n")
    entrada.flush()
    while not body.calls:
        time.sleep(0.01)
    t0 = time.monotonic()
    entrada.close()
    worker.join(5.0)
    assert time.monotonic() - t0 < 2.0
    assert json.loads(out.getvalue().splitlines()[0]) == {"id": 1, "ok": False, "erro": "interrompida"}


def test_parar_logo_depois_da_meia_volta_enfileirada_nao_se_perde():
    body = _FakeBody()
    entrada, out, worker = _abre(body)
    entrada.write(json.dumps({"id": 1, "cmd": "posture", "nome": "lenta"}) + "\n")
    entrada.flush()
    while not body.calls:
        time.sleep(0.01)
    entrada.write(json.dumps({"id": 2, "cmd": "meia_volta", "cfg": {**_CFG, "passo_m": 0.42}}) + "\n")
    entrada.write(json.dumps({"cmd": "parar"}) + "\n")
    entrada.flush()
    time.sleep(0.2)
    body.solta_lenta.set()
    entrada.close()
    worker.join(5.0)
    respostas = [json.loads(line) for line in out.getvalue().splitlines()]
    assert {"id": 2, "ok": False, "erro": "interrompida"} in respostas


def test_subprocess_body_meia_volta():
    body = SubprocessBody("", "", command=[sys.executable, "-c", FAKE_WORKER])
    assert body.meia_volta(_CFG, lambda: False) == (True, "")
    assert body.meia_volta({**_CFG, "passo_m": 0.3}, lambda: False) == (False, "tempo esgotado")
    body.shutdown()


def test_meia_volta_interrompida_antes_da_escrita_nao_manda_a_ordem(tmp_path):
    log = tmp_path / "ordens"
    worker = FAKE_WORKER.replace(
        "serve(Body(), sys.stdin, sys.stdout)",
        f"serve(Body(), (open({str(log)!r}, 'a').write(l) or l for l in sys.stdin), sys.stdout)",
    )
    body = SubprocessBody("", "", command=[sys.executable, "-c", worker])
    assert body.meia_volta(_CFG, lambda: True) == (False, "interrompida")
    body.shutdown()
    assert "meia_volta" not in log.read_text()
