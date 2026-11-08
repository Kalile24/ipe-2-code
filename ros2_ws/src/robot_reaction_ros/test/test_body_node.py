"""Testes do body_node sem robô: o corpo (G1ArmController) e a voz são dublês.

As rotinas chegam pela ação /reaction/rotina, de um cliente de verdade no mesmo processo.
"""
import json
import threading
import time

import pytest
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter

import robot_reaction_ros.body_node as node_mod
from robot_reaction_interfaces.action import Rotina
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

PASSOS = [
    {"postura": "sentido"},
    {"fala": "Olá, aspirante"},
    {"postura": "descansar"},
    {"postura": "a_vontade"},
    {"fala": "Bom ver o senhor"},
]


class _FakeBody:
    def __init__(self, init_ok=True):
        self.calls = []
        self.init_ok = init_ok
        self.gate = None  # threading.Event: segura uma postura em andamento
        self.so_equilibrio = None
        self.stop_em = None  # instante do primeiro stop
        self.meia_volta_gate = None  # threading.Event: segura a meia-volta; stop() a solta
        self.meia_volta_res = (True, "")

    def initialize(self, so_equilibrio=False):
        self.calls.append("initialize")
        self.so_equilibrio = so_equilibrio
        return self.init_ok

    def velocity(self, vx, vyaw):
        self.calls.append(("velocidade", vx, vyaw))

    def stop(self):
        self.calls.append("stop")
        if self.stop_em is None:
            self.stop_em = time.monotonic()
        if self.meia_volta_gate is not None:
            self.meia_volta_gate.set()

    def posture(self, nome):
        self.calls.append(nome)
        if self.gate is not None:
            self.gate.wait(5)
        return True

    def meia_volta(self, cfg, deve_parar):
        if deve_parar():  # como o SubprocessBody: interrompida antes da escrita, nada é mandado
            return False, "interrompida"
        self.calls.append("meia_volta")
        if self.meia_volta_gate is not None:
            self.meia_volta_gate.wait(5)
            return False, "interrompida"
        return self.meia_volta_res

    def shutdown(self):
        self.calls.append("shutdown")


def _dets(node, *caixas):
    """Entrega ao nó uma Detection2DArray com (nome, center_x, size_y)."""
    msg = Detection2DArray()
    for nome, cx, sy in caixas:
        hypothesis = ObjectHypothesisWithPose()
        hypothesis.id = nome
        detection = Detection2D()
        detection.bbox.center.x = float(cx)
        detection.bbox.size_y = float(sy)
        detection.results.append(hypothesis)
        msg.detections.append(detection)
    node._on_detections(msg)


def _until(cond, timeout=5.0):
    fim = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < fim, "a condição não aconteceu"
        time.sleep(0.01)


def _wait(future, timeout=5.0):
    fim = time.monotonic() + timeout
    while not future.done():
        assert time.monotonic() < fim, "o body_node não respondeu"
        time.sleep(0.01)
    return future.result()


class _Env:
    def __init__(self, node, client):
        self.node = node
        self.client = client

    def send(self, passos=PASSOS, pessoa="gil", passos_json=None, voz=False):
        """Manda a rotina; devolve (aceita, future do resultado ou None)."""
        goal = Rotina.Goal(
            pessoa=pessoa, passos_json=passos_json if passos_json is not None else json.dumps(passos), voz=voz
        )
        handle = _wait(self.client.send_goal_async(goal))
        return handle.accepted, (handle.get_result_async() if handle.accepted else None), handle

    def run(self, **kw):
        aceita, resultado, _ = self.send(**kw)
        assert aceita
        return _wait(resultado).result


@pytest.fixture
def make_node(monkeypatch):
    status, spoken, cleanup = [], [], []
    monkeypatch.setattr(node_mod.BodyNode, "_publish", lambda self, text: status.append(text))

    def speak(text, url, timeout_s):
        spoken.append(text)

    # Estágios padrão do teste sem virar/aproximar: os testes antigos não esperam pela aproximação.
    def make(body=None, armed=False, factory_error=None, wait_init=True, estagios="fala,posturas", params=()):
        def factory(poses_dir, network_interface, rest_forward_pulse):
            if factory_error is not None:
                raise factory_error
            return body

        args = ["pausa_s:=0.0", f"armed:={'true' if armed else 'false'}", f"estagios:={estagios}", *params]
        rclpy.init(args=["--ros-args", *[a for p in args for a in ("-p", p)]])
        n = node_mod.BodyNode(body_factory=factory, speak=speak)
        if n._init_thread is not None and wait_init:
            n._init_thread.join(5)
        client_node = rclpy.create_node("cliente_teste")
        client = ActionClient(client_node, Rotina, "/reaction/rotina")
        executor = MultiThreadedExecutor()
        executor.add_node(n)
        executor.add_node(client_node)
        threading.Thread(target=executor.spin, daemon=True).start()
        assert client.wait_for_server(timeout_sec=5)
        cleanup.append((executor, n, client_node, client))
        return _Env(n, client)

    yield make, status, spoken
    for executor, n, client_node, client in cleanup:
        executor.shutdown()
        client.destroy()
        client_node.destroy_node()
        n.destroy_node()
    rclpy.shutdown()


def test_disarmed_speaks_but_only_logs_postures(make_node):
    make, status, spoken = make_node
    env = make()
    resultado = env.run()
    assert resultado.sucesso
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]
    assert [s for s in status if s.startswith("dry_run")] == [
        "dry_run postura sentido",
        "dry_run postura descansar",
        "dry_run postura a_vontade",
    ]
    assert status[-1] == "rotina de gil: fim"


def test_armed_initializes_then_runs_postures_in_order(make_node):
    make, status, spoken = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    assert "pronto: em equilíbrio, esperando reconhecimento" in status
    assert env.run().sucesso
    assert body.calls == ["initialize", "sentido", "descansar", "a_vontade"]
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]


def test_failed_initialization_falls_back_to_dry_run(make_node):
    make, status, _ = make_node
    body = _FakeBody(init_ok=False)
    env = make(body=body, armed=True)
    env.run()
    assert body.calls == ["initialize"]
    assert "dry_run postura sentido" in status


def test_factory_error_is_reported_and_node_stays_up(make_node):
    make, status, _ = make_node
    env = make(armed=True, factory_error=ImportError("sem poses"))
    assert any(s.startswith("falha na inicialização") and "sem poses" in s for s in status)
    assert env.run().sucesso


def test_second_routine_while_busy_is_rejected_and_the_client_knows(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    body.gate = threading.Event()
    aceita, primeira, _ = env.send()
    assert aceita
    segunda_aceita, _, _ = env.send()
    body.gate.set()
    assert _wait(primeira).result.sucesso
    assert not segunda_aceita
    assert "rotina de gil rejeitada: ocupado" in status
    assert body.calls.count("sentido") == 1


def test_routine_during_initialization_is_rejected(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    gate = threading.Event()
    initialize = body.initialize
    body.initialize = lambda so_equilibrio=False: gate.wait(5) and initialize(so_equilibrio)
    env = make(body=body, armed=True, wait_init=False)
    aceita, _, _ = env.send()
    gate.set()
    env.node._init_thread.join(5)
    assert not aceita
    assert env.run().sucesso  # depois de pronto, aceita


@pytest.mark.parametrize(
    "kw",
    [
        {"passos_json": "não é json"},
        {"passos_json": "{}"},
        {"passos": [{"postura": "sentido"}]},  # sem a_vontade
        {"pessoa": " "},
    ],
)
def test_invalid_goals_are_rejected(make_node, kw):
    make, status, spoken = make_node
    env = make()
    aceita, _, _ = env.send(**kw)
    assert not aceita
    assert status[-1].startswith("rotina rejeitada")
    assert spoken == []


def test_armed_cannot_change_after_start(make_node):
    make, _, _ = make_node
    env = make()
    result = env.node.set_parameters([Parameter("armed", Parameter.Type.BOOL, True)])
    assert not result[0].successful


def test_cancel_stops_after_the_current_step_and_releases_the_arms(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    body.gate = threading.Event()
    aceita, resultado, handle = env.send()
    assert aceita
    _wait(handle.cancel_goal_async())
    body.gate.set()
    final = _wait(resultado)
    assert not final.result.sucesso
    assert body.calls == ["initialize", "sentido", "stop", "a_vontade"]  # para de andar na hora
    assert "rotina de gil: interrompida" in status


def test_long_pause_ends_on_cancel(make_node):
    make, _, _ = make_node
    env = make(body=_FakeBody(), armed=True)
    passos = [{"postura": "descansar"}, {"pausa": 120}, {"postura": "a_vontade"}]
    aceita, resultado, handle = env.send(passos=passos)
    assert aceita
    time.sleep(0.2)
    inicio = time.monotonic()
    _wait(handle.cancel_goal_async())
    _wait(resultado, timeout=3)
    assert time.monotonic() - inicio < 3


def test_shutdown_waits_for_current_step_then_releases(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    body.gate = threading.Event()
    aceita, _, _ = env.send()
    assert aceita
    threading.Timer(0.2, body.gate.set).start()
    env.node.shutdown(timeout_s=5)
    # Parou de andar na hora, parou depois do sentido em andamento (não começou o descansar), fez o
    # a_vontade e só então soltou o arm_sdk.
    assert body.calls == ["initialize", "sentido", "stop", "a_vontade", "shutdown"]
    assert not env.send()[0]  # encerrando: nenhuma rotina nova


TODOS = "virar,aproximar,fala,posturas"


def test_armed_turns_then_runs_the_routine(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios="virar,fala,posturas")
    _dets(env.node, ("gil", 320, 120), ("cmt", 100, 200))
    assert env.run().sucesso
    assert body.calls[:2] == ["initialize", "stop"]  # pronto no primeiro passo: parou
    assert "sentido" in body.calls
    assert "virar: desvio=+0.00 caixa=120px vx=0.00 vyaw=0.00 (pronto)" in status


def test_approach_sends_velocities_until_ready(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=TODOS)
    _dets(env.node, ("gil", 352, 50))  # desvio +0,1 (de frente), longe
    aceita, resultado, _ = env.send()
    assert aceita
    _until(lambda: ("velocidade", 0.2, 0.0) in body.calls)
    _dets(env.node, ("gil", 352, 120))
    assert _wait(resultado).result.sucesso
    assert body.calls.index("stop") < body.calls.index("sentido")
    assert "aproximar: desvio=+0.10 caixa=50px vx=0.20 vyaw=0.00 (andando)" in status


def test_lost_face_gives_up_without_greeting(make_node):
    make, status, spoken = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=TODOS, params=["desistir_s:=0.3", "perda_rosto_s:=0.1"])
    resultado = env.run()
    assert not resultado.sucesso and resultado.mensagem == "desistiu: rosto perdido"
    assert "sentido" not in body.calls and body.calls[-1] == "stop"
    assert spoken == ["Perdi Gil de vista"]  # só ao desistir, uma vez
    assert status[-1] == "rotina de gil: desistiu: rosto perdido"


def test_lost_sight_warning_can_be_turned_off(make_node):
    make, status, spoken = make_node
    env = make(body=_FakeBody(), armed=True, estagios=TODOS,
               params=["desistir_s:=0.3", "perda_rosto_s:=0.1", "avisos_voz:=false"])
    assert env.run().mensagem == "desistiu: rosto perdido"
    assert spoken == []


def test_running_out_of_time_says_nothing(make_node):
    make, status, spoken = make_node
    env = make(body=_FakeBody(), armed=True, estagios=TODOS, params=["tempo_max_s:=0.2"])
    _dets(env.node, ("gil", 320, 50))
    assert env.run().mensagem == "desistiu: tempo esgotado"
    assert spoken == []


def test_cancel_during_approach_stops_at_once_and_skips_routine(make_node):
    make, status, spoken = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=TODOS)
    _dets(env.node, ("gil", 320, 50))
    aceita, resultado, handle = env.send()
    assert aceita
    _until(lambda: ("velocidade", 0.2, 0.0) in body.calls)
    inicio = time.monotonic()
    _wait(handle.cancel_goal_async())
    _until(lambda: body.stop_em is not None)
    assert body.stop_em - inicio < 0.2
    final = _wait(resultado)
    assert not final.result.sucesso
    assert all(c == "initialize" or c == "stop" or c[0] == "velocidade" for c in body.calls)  # nenhuma postura
    assert spoken == []
    assert "rotina de gil: interrompida" in status


def test_disarmed_only_measures_for_two_seconds(make_node):
    make, status, spoken = make_node
    env = make(estagios=TODOS)
    _dets(env.node, ("gil", 352, 50))
    inicio = time.monotonic()
    assert env.run().sucesso
    assert time.monotonic() - inicio >= 2.0
    assert "aproximar: desvio=+0.10 caixa=50px vx=0.20 vyaw=0.00 (andando)" in status
    assert "dry_run postura sentido" in status
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]


def test_stages_filter_the_routine(make_node):
    make, status, spoken = make_node
    env = make(estagios="fala")
    assert env.run().sucesso
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]
    assert not [s for s in status if s.startswith("dry_run")]


def test_empty_filtered_routine_succeeds(make_node):
    make, _, spoken = make_node
    env = make(estagios="posturas")
    assert env.run(passos=[{"fala": "Olá"}]).sucesso
    assert spoken == []


def test_invalid_stages_param_stops_the_node(make_node):
    make, _, _ = make_node
    with pytest.raises(ValueError, match="posturas"):
        make(estagios="pular")


def test_balance_only_failure_speaks_and_rejects_routines(make_node):
    make, status, spoken = make_node
    body = _FakeBody(init_ok=False)
    env = make(body=body, armed=True, params=["so_equilibrio:=true"])
    assert body.so_equilibrio is True
    assert spoken == ["Não estou em equilíbrio, não vou começar."]
    assert not env.send()[0]
    assert not [s for s in status if s.startswith("dry_run")]


MV = "posturas,meia_volta"
POSTURA = [{"postura": "a_vontade"}]


def test_armado_faz_meia_volta_depois_da_rotina(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=MV)
    r = env.run(passos=POSTURA)
    assert body.calls == ["initialize", "a_vontade", "meia_volta"]
    assert r.sucesso and r.mensagem == "meia_volta: fim"
    assert status[-2:] == ["meia_volta: fim", "rotina de gil: fim"]


def test_armado_publica_girando_antes_do_fim(make_node):
    make, status, _ = make_node
    make(body=_FakeBody(), armed=True, estagios=MV).run(passos=POSTURA)
    assert status.index("meia_volta: girando") < status.index("meia_volta: fim")


def test_passo_fora_da_faixa_para_o_no(make_node):
    make, _, _ = make_node
    with pytest.raises(ValueError, match="passo_m"):
        make(params=["passo_m:=3.0"])


def test_meia_volta_que_falha_ainda_conta_como_cumprimento(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    body.meia_volta_res = (False, "tempo esgotado")
    r = make(body=body, armed=True, estagios=MV).run(passos=POSTURA)
    assert r.sucesso and r.mensagem == "meia_volta: falhou (tempo esgotado)"
    assert status[-2:] == ["meia_volta: falhou (tempo esgotado)", "rotina de gil: fim"]


def test_rotina_que_falha_nao_faz_meia_volta(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    body.posture = lambda nome: False
    r = make(body=body, armed=True, estagios=MV).run(passos=POSTURA)
    assert not r.sucesso and "meia_volta" not in body.calls


def test_desarmado_so_registra_meia_volta(make_node):
    make, status, _ = make_node
    r = make(estagios=MV).run(passos=POSTURA)
    assert "dry_run meia_volta" in status
    assert r.sucesso and r.mensagem == "meia_volta: dry_run"


def test_sem_estagio_nao_faz_meia_volta(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    r = make(body=body, armed=True, estagios="posturas").run(passos=POSTURA)
    assert r.sucesso and r.mensagem == "" and "meia_volta" not in body.calls


def test_cancelar_durante_meia_volta_para_o_corpo(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=MV)
    body.meia_volta_gate = threading.Event()
    aceita, resultado, handle = env.send(passos=POSTURA)
    assert aceita
    _until(lambda: "meia_volta" in body.calls)
    _wait(handle.cancel_goal_async())
    final = _wait(resultado)
    assert "stop" in body.calls
    assert final.result.sucesso and final.result.mensagem == "meia_volta: falhou (interrompida)"
    assert final.status == 5  # STATUS_CANCELED
    assert "meia_volta: falhou (interrompida)" in status


def test_shutdown_durante_meia_volta_para_o_corpo(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=MV)
    body.meia_volta_gate = threading.Event()
    aceita, _, _ = env.send(passos=POSTURA)
    assert aceita
    _until(lambda: "meia_volta" in body.calls)
    inicio = time.monotonic()
    env.node.shutdown(timeout_s=5)
    assert "stop" in body.calls and time.monotonic() - inicio < 3
    assert body.calls[-1] == "shutdown"


def test_cancelamento_depois_da_rotina_nao_manda_a_meia_volta(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios=MV)
    original = body.posture

    def posture(nome):  # o cancelamento chega logo depois da última postura
        original(nome)
        env.node._interromper.set()
        return True

    body.posture = posture
    r = env.run(passos=POSTURA)
    assert "meia_volta" not in body.calls
    assert r.sucesso is False or r.mensagem != "meia_volta: fim"


def test_desarmado_nao_chama_o_corpo_na_meia_volta(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    make(body=body, armed=False, estagios=MV).run(passos=POSTURA)
    assert "meia_volta" not in body.calls


# --- posição mantida (comandos de voz) ---

SENTIDO = [{"postura": "sentido"}]
CONTINENCIA = [{"postura": "continencia"}]
A_VONTADE = [{"postura": "a_vontade"}]


def _voz(env, passos):
    return env.run(passos=passos, pessoa="voz", voz=True)


def test_voz_mantem_a_posicao_sem_a_vontade(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    assert _voz(env, SENTIDO).sucesso
    assert body.calls == ["initialize", "sentido"]
    assert env.node._mantida == "sentido"
    assert env.node._corpo == "mantendo:sentido"


def test_voz_nao_aproxima_nem_faz_meia_volta(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, estagios="virar,aproximar,fala,posturas,meia_volta")
    assert _voz(env, SENTIDO).sucesso
    assert body.calls == ["initialize", "sentido"]  # nenhuma velocidade, nenhum stop, nenhuma meia_volta


def test_trocar_de_continencia_para_sentido(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    _voz(env, CONTINENCIA)
    _voz(env, SENTIDO)
    assert body.calls == ["initialize", "continencia", "desc_arma", "sentido"]


def test_a_vontade_solta_a_posicao(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    _voz(env, SENTIDO)
    _voz(env, A_VONTADE)
    assert env.node._mantida is None
    assert env.node._corpo == "livre"
    assert body.calls[-1] == "a_vontade"


def test_cumprimento_recusado_com_posicao_mantida(make_node):
    make, status, _ = make_node
    env = make(body=_FakeBody(), armed=True)
    _voz(env, SENTIDO)
    assert not env.send()[0]
    assert "rotina de gil rejeitada: posicao mantida" in status


def test_postura_que_falha_limpa_a_posicao(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    _voz(env, SENTIDO)
    body.posture = lambda nome: False
    assert not _voz(env, CONTINENCIA).sucesso
    assert env.node._mantida is None
    assert env.node._corpo == "livre"


def test_corpo_publica_livre_na_partida_e_rotina_durante_a_execucao(make_node):
    from std_msgs.msg import String
    from rclpy.qos import DurabilityPolicy, QoSProfile

    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    recebidos = []
    sub = env.client._node.create_subscription(
        String, "/reaction/corpo", lambda m: recebidos.append(m.data),
        QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    _until(lambda: recebidos == ["livre"])  # estado de antes da assinatura chega (TRANSIENT_LOCAL)
    body.gate = threading.Event()
    aceita, resultado, _ = env.send(passos=SENTIDO + A_VONTADE)
    assert aceita
    _until(lambda: env.node._corpo == "rotina")
    body.gate.set()
    _wait(resultado)
    _until(lambda: recebidos[-2:] == ["rotina", "livre"])


def test_tempo_limite_faz_a_vontade(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, params=("posicao_max_s:=0.1",))
    _voz(env, SENTIDO)
    _until(lambda: body.calls[-1] == "a_vontade", timeout=4)
    _until(lambda: env.node._corpo == "livre")
    assert env.node._mantida is None
    assert "posicao mantida: tempo esgotado, a_vontade" in status


def test_tempo_limite_nao_disputa_rotina(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, params=("posicao_max_s:=0.1",))
    _voz(env, SENTIDO)
    env.node._busy.acquire()  # uma rotina em andamento
    time.sleep(1.5)  # passa por mais de uma conferência
    assert "a_vontade" not in body.calls
    env.node._busy.release()
    _until(lambda: body.calls[-1] == "a_vontade", timeout=4)  # tenta de novo depois


def test_tempo_limite_nao_vale_depois_do_ctrl_c(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True, params=("posicao_max_s:=0.1",))
    _voz(env, SENTIDO)
    env.node._stop.set()
    time.sleep(1.5)
    assert "a_vontade" not in body.calls


def test_posicao_max_s_invalida_para_o_no(make_node):
    make, _, _ = make_node
    with pytest.raises(ValueError):
        make(params=("posicao_max_s:=0.0",))


def test_ctrl_c_com_posicao_mantida_solta_os_bracos(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    _voz(env, SENTIDO)
    env.node.shutdown(timeout_s=5)
    assert body.calls[-1] == "shutdown"


def test_goal_de_cumprimento_ainda_exige_a_vontade(make_node):
    make, _, _ = make_node
    env = make(body=_FakeBody(), armed=True)
    assert not env.send(passos=SENTIDO)[0]  # sem voz: tem que terminar em a_vontade
    assert env.send(passos=SENTIDO, voz=True)[0]
