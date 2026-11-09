from __future__ import annotations

import functools
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, fields
from typing import Callable

import rclpy
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import SetParametersResult
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.approach import (
    DESISTIU_ROSTO,
    DESISTIU_TEMPO,
    PRONTO,
    ApproachConfig,
    escolher_caixa,
    passo_aproximacao,
    validar_operacao,
)
from core.comandos_voz import transicao
from core.meia_volta import MeiaVoltaConfig
from core.pessoas import nome_falado
from core.piper_voice import DEFAULT_URL, say
from core.reaction_policy import A_VONTADE, ReactionConfigError, validate_steps
from core.routine import run_routine
from core.stages import filter_steps, parse_stages
from robot_reaction_interfaces.action import Rotina

# Tempos máximos. O sigterm_timeout do rotina.launch.py tem que cobrir o pior caso do Ctrl+C:
# a postura em andamento + o a_vontade + a ordem de shutdown + a espera do processo.
POSTURA_TIMEOUT_S = 120.0
LIMITE_POSICAO_VERIFICA_S = 1.0  # de quanto em quanto tempo o limite da posição mantida é conferido
INICIALIZACAO_TIMEOUT_S = 120.0
MEIA_VOLTA_TIMEOUT_S = 60.0
ESPERA_ROTINA_S = 2 * POSTURA_TIMEOUT_S + MEIA_VOLTA_TIMEOUT_S + 10.0
SHUTDOWN_TIMEOUT_S = 60.0
ESPERA_PROCESSO_S = 10.0
# Desarmado o robô não se mexe: virar/aproximar só medem (status com a caixa do rosto) por isto.
MEDIR_DESARMADO_S = 2.0
PASSO_APROXIMACAO_S = 0.1  # laço a ~10 Hz
NAO_EQUILIBRIO = "Não estou em equilíbrio, não vou começar."


class SubprocessBody:
    """O corpo num processo sem ROS (body_worker): rclpy e SDK da Unitree não convivem.

    Mesma interface que o body_node espera (initialize/posture/shutdown); cada chamada é uma
    linha JSON com um `id` para o body_worker, e só a resposta com esse `id` vale. Uma chamada
    por vez (lock): o shutdown do Ctrl+C espera a postura em andamento em vez de se misturar a ela.
    velocity/stop não têm resposta nem esperam esse lock: só escrevem a linha.
    """

    def __init__(
        self,
        poses_dir: str,
        network_interface: str,
        rest_forward_pulse: bool = True,
        command: list[str] | None = None,
        posture_timeout_s: float = POSTURA_TIMEOUT_S,
    ) -> None:
        command = command or [
            sys.executable, "-m", "robot_reaction_ros.body_worker", poses_dir, network_interface,
            "com_passo" if rest_forward_pulse else "sem_passo",
        ]
        self._posture_timeout_s = posture_timeout_s
        self._lock = threading.Lock()  # uma chamada com resposta por vez
        self._escrita = threading.Lock()  # só a escrita da linha: velocity/stop não esperam postura
        self._next_id = 0
        # Binário sem buffer: o readline não lê adiantado, então o select nunca perde uma linha
        # que já chegou. stderr herdado: o log do G1ArmController aparece junto com o do launch.
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        hello = self._read(timeout_s=60.0, ordem_id=None)
        if not hello.get("ok"):
            self._proc.kill()
            raise RuntimeError(f"body_worker não subiu: {hello.get('erro', hello)}")

    def _read(self, timeout_s: float, ordem_id: int | None) -> dict:
        fim = time.monotonic() + timeout_s
        while True:
            restante = fim - time.monotonic()
            prontos = select.select([self._proc.stdout], [], [], restante)[0] if restante > 0 else []
            line = self._proc.stdout.readline() if prontos else b""
            if not line:
                return {"ok": False, "erro": f"sem resposta do body_worker em {timeout_s:.0f} s"}
            resposta = json.loads(line)
            if ordem_id is None or resposta.get("id") == ordem_id:
                return resposta
            # resposta atrasada de uma ordem em que já desistimos de esperar: descartada

    def _call_erro(
        self, ordem: dict, timeout_s: float, deve_parar: Callable[[], bool] | None = None
    ) -> tuple[bool, str]:
        with self._lock:
            if self._proc.poll() is not None:
                return False, "body_worker morto"
            self._next_id += 1
            ordem = {"id": self._next_id, **ordem}
            with self._escrita:
                # Conferido com a escrita presa: o stop() também escreve sob este lock, então ou a
                # ordem nunca sai ou o "parar" vem depois dela (o leitor do worker limparia um anterior).
                if deve_parar is not None and deve_parar():
                    return False, "interrompida"
                if not self._write_preso(ordem):
                    return False, "body_worker morto"
            resposta = self._read(timeout_s, ordem["id"])
            return bool(resposta.get("ok")), str(resposta.get("erro", ""))

    def _call(self, ordem: dict, timeout_s: float) -> bool:
        return self._call_erro(ordem, timeout_s)[0]

    def _write_preso(self, ordem: dict) -> bool:
        """Escreve a linha; quem chama já segura `_escrita`."""
        try:
            self._proc.stdin.write((json.dumps(ordem) + "\n").encode())
        except BrokenPipeError:
            return False
        return True

    def _write(self, ordem: dict) -> bool:
        with self._escrita:
            return self._write_preso(ordem)

    def initialize(self, so_equilibrio: bool = False) -> bool:
        return self._call(
            {"cmd": "initialize", "so_equilibrio": so_equilibrio}, timeout_s=INICIALIZACAO_TIMEOUT_S
        )

    def velocity(self, vx: float, vyaw: float) -> None:
        """Sem resposta: o body_worker atende na hora, mesmo com uma postura em andamento."""
        self._write({"cmd": "velocidade", "vx": vx, "vyaw": vyaw})

    def stop(self) -> None:
        self._write({"cmd": "parar"})

    def posture(self, nome: str) -> bool:
        return self._call({"cmd": "posture", "nome": nome}, timeout_s=self._posture_timeout_s)

    def meia_volta(self, cfg: dict, deve_parar: Callable[[], bool]) -> tuple[bool, str]:
        """Não manda a ordem se `deve_parar()` já vale: ver _call_erro."""
        return self._call_erro(
            {"cmd": "meia_volta", "cfg": cfg}, timeout_s=MEIA_VOLTA_TIMEOUT_S, deve_parar=deve_parar
        )

    def shutdown(self) -> None:
        try:
            self._call({"cmd": "shutdown"}, timeout_s=SHUTDOWN_TIMEOUT_S)
        finally:
            if self._proc.poll() is None:
                try:
                    self._proc.wait(ESPERA_PROCESSO_S)
                except subprocess.TimeoutExpired:
                    self._proc.kill()


class BodyNode(Node):
    """Único dono dos braços e da voz: servidor da ação /reaction/rotina (uma rotina por vez).

    Os braços são comandados pelo body_worker (processo sem ROS, ver body_worker.py).

    Desarmado (padrão): fala de verdade, mas as posturas só aparecem no log (dry-run).
    Armado (`armed:=true`, só na partida): ao subir faz a inicialização do F1+UP e depois executa
    as posturas. Uma rotina chegando enquanto inicializa ou executa outra é recusada (o
    reaction_node fica sabendo). Status em /reaction/rotina_status e no feedback da ação.
    Antes da rotina (estágios `virar`/`aproximar`) vira e anda até a pessoa pela caixa do rosto
    nas detecções; os estágios `fala`/`posturas` filtram a rotina.
    Cancelar a ação ou Ctrl+C: para de andar na hora; uma postura em andamento termina, os braços
    voltam (a_vontade) e solta o arm_sdk.
    """

    def __init__(
        self,
        body_factory: Callable[..., object] = SubprocessBody,
        speak: Callable[..., None] = say,
    ) -> None:
        super().__init__("body_node")
        self.declare_parameter("armed", False)
        # "" = as poses instaladas com o pacote (share/robot_reaction_ros/poses)
        self.declare_parameter("poses_dir", "")
        self.declare_parameter("network_interface", "eth0")
        self.declare_parameter("pausa_s", 0.5)
        # true: o descansar dá um passo curto para frente (compensação de equilíbrio do ~/hhhh)
        self.declare_parameter("passo_descansar", True)
        self.declare_parameter("tts_url", DEFAULT_URL)
        self.declare_parameter("tts_timeout_s", 60.0)
        self.declare_parameter("estagios", "virar,aproximar,fala,posturas,meia_volta")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        # true: inicializa só se já estiver em equilíbrio (FSM 801), sem damp → em pé (partida pelo controle)
        self.declare_parameter("so_equilibrio", False)
        self.declare_parameter("posicao_max_s", 300.0)  # posição mantida por voz: depois disto, a_vontade sozinho
        self.declare_parameter("avisos_voz", True)  # depuração: "Perdi <nome> de vista" ao desistir
        for campo in fields(ApproachConfig):
            self.declare_parameter(campo.name, campo.default)
        for campo in fields(MeiaVoltaConfig):
            self.declare_parameter(campo.name, campo.default)
        # ValueError com os estágios válidos: derruba o nó na partida
        self._estagios = parse_stages(str(self.get_parameter("estagios").value))
        self._approach = ApproachConfig(**{
            # `is True` nos bool: um "true" string seria verdadeiro; int/float convertidos (9 vira 9.0)
            c.name: self.get_parameter(c.name).value is True
            if isinstance(c.default, bool)
            else type(c.default)(self.get_parameter(c.name).value)
            for c in fields(ApproachConfig)
        })
        self._meia_volta = MeiaVoltaConfig(**{
            c.name: type(c.default)(self.get_parameter(c.name).value) for c in fields(MeiaVoltaConfig)
        })
        validar_operacao(asdict(self._meia_volta))  # fora da faixa: o nó não sobe, como parse_stages
        self._so_equilibrio = self.get_parameter("so_equilibrio").value is True
        self._avisos_voz = self.get_parameter("avisos_voz").value is True
        self._posicao_max_s = float(self.get_parameter("posicao_max_s").value)
        if not self._posicao_max_s > 0:
            raise ValueError(f"posicao_max_s tem que ser maior que 0, veio {self._posicao_max_s}")
        self._pausa_s = float(self.get_parameter("pausa_s").value)
        self._speak = functools.partial(
            speak,
            url=self.get_parameter("tts_url").value,
            timeout_s=float(self.get_parameter("tts_timeout_s").value),
        )

        self._body = None
        self._ready = False  # inicializado (FSM 801): só então as posturas mexem o braço
        self._stop = threading.Event()  # Ctrl+C: nenhuma rotina nova
        self._interromper = threading.Event()  # cancelamento ou Ctrl+C: encerra a rotina atual
        self._idle = threading.Event()  # nenhuma rotina em execução
        self._idle.set()
        self._busy = threading.Lock()  # preso durante a inicialização e durante cada rotina
        self._init_thread: threading.Thread | None = None
        self._mantida: str | None = None  # posição mantida por um comando de voz (só mexe com _busy preso)
        self._mantida_desde = 0.0
        self._vistos: dict[str, tuple[tuple[float, float], float]] = {}  # nome → ((center_x, size_y), instante)

        grupo = ReentrantCallbackGroup()  # as detecções chegam enquanto a ação executa
        self._status_pub = self.create_publisher(String, "/reaction/rotina_status", 10)
        # TRANSIENT_LOCAL: o nó de voz e o reaction_node que subirem depois veem o último estado.
        self._corpo_pub = self.create_publisher(
            String, "/reaction/corpo", QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )
        self._corpo = ""
        self._publicar_corpo("livre")
        self._detections = self.create_subscription(
            Detection2DArray,
            self.get_parameter("detections_topic").value,
            self._on_detections,
            QoSProfile(depth=1),
            callback_group=grupo,
        )
        self.create_timer(LIMITE_POSICAO_VERIFICA_S, self._conferir_limite, callback_group=grupo)
        self._server = ActionServer(
            self,
            Rotina,
            "/reaction/rotina",
            execute_callback=self._execute,
            goal_callback=self._on_goal,
            cancel_callback=self._on_cancel,
            callback_group=grupo,
        )
        # `armed` só vale na partida: armar no meio faria o robô cair em damp sem aviso.
        self.add_on_set_parameters_callback(self._on_set_parameters)

        # `is True`: um "true" que chegasse como string seria verdadeiro e armaria o braço.
        if self.get_parameter("armed").value is True:
            poses_dir = self.get_parameter("poses_dir").value or os.path.join(
                get_package_share_directory("robot_reaction_ros"), "poses"
            )
            args = (
                poses_dir,
                self.get_parameter("network_interface").value,
                self.get_parameter("passo_descansar").value is True,
            )
            self._busy.acquire()  # nenhuma rotina enquanto inicializa
            self._init_thread = threading.Thread(target=self._initialize, args=(body_factory, *args), daemon=True)
            self._init_thread.start()
        else:
            self._publish("desarmado: posturas só no log, fala de verdade")

    def _publish(self, text: str) -> None:
        self.get_logger().info(text)
        try:
            self._status_pub.publish(String(data=text))
        except Exception:  # depois do Ctrl+C o contexto ROS já fechou; o log basta
            pass

    def _publicar_corpo(self, estado: str) -> None:
        self._corpo = estado
        try:
            self._corpo_pub.publish(String(data=estado))
        except Exception:  # depois do Ctrl+C o contexto ROS já fechou
            pass

    def _estado_corpo(self) -> str:
        return f"mantendo:{self._mantida}" if self._mantida else "livre"

    def _conferir_limite(self) -> None:
        """Posição mantida por mais de posicao_max_s: à vontade sozinho. Nunca disputa uma rotina."""
        if self._stop.is_set() or self._mantida is None:
            return
        if time.monotonic() - self._mantida_desde < self._posicao_max_s:
            return
        if not self._busy.acquire(blocking=False):  # rotina em andamento: tenta de novo daqui a pouco
            return
        self._idle.clear()  # o shutdown espera por nós
        try:
            if self._stop.is_set() or self._mantida is None:
                return
            self._publicar_corpo("rotina")
            try:
                ok = self._posture(A_VONTADE)
            except Exception as exc:
                self._publish(f"posicao mantida: a_vontade falhou ({exc!r})")
                ok = False
            if ok:
                self._mantida = None
                self._publish("posicao mantida: tempo esgotado, a_vontade")
            else:  # braços ainda presos: tenta de novo daqui a posicao_max_s, não a cada segundo
                self._mantida_desde = time.monotonic()
                self._publish("posicao mantida: a_vontade falhou")
        finally:
            self._publicar_corpo(self._estado_corpo())
            self._idle.set()
            self._busy.release()

    def _on_set_parameters(self, params: list) -> SetParametersResult:
        if any(p.name == "armed" for p in params):
            return SetParametersResult(successful=False, reason="armed só vale na partida (reinicie o nó)")
        for p in params:
            if p.name == "estagios":
                try:
                    novos = parse_stages(str(p.value))
                except ValueError as exc:
                    return SetParametersResult(successful=False, reason=str(exc))
                # Sob _busy: uma rotina em andamento não troca de estágios no meio.
                if not self._busy.acquire(blocking=False):
                    return SetParametersResult(successful=False, reason="rotina em andamento: tente quando terminar")
                try:
                    self._estagios = novos
                finally:
                    self._busy.release()
        return SetParametersResult(successful=True)

    def _initialize(self, body_factory: Callable[..., object], *args: object) -> None:
        try:
            self._publish("inicializando: damp → em pé → equilíbrio (robô no suporte)")
            try:
                self._body = body_factory(*args)
                self._ready = self._body.initialize(self._so_equilibrio)
            except Exception as exc:  # sem SDK, sem poses ou sem DDS
                self._publish(f"falha na inicialização: {exc!r}")
            if self._ready:
                self._publish("pronto: em equilíbrio, esperando reconhecimento")
            elif self._so_equilibrio:
                # Pelo controle não há terminal olhando: a recusa é falada. Sem dry-run neste modo.
                self._stop.set()  # recusa todas as rotinas
                self._publish("falha na inicialização: não está em equilíbrio (FSM 801); rotinas recusadas")
                try:
                    self._speak(NAO_EQUILIBRIO)
                except Exception as exc:  # sem caixa ou sem Piper: o log basta
                    self._publish(f"fala falhou: {exc!r}")
            elif self._body is not None:
                self._publish("falha na inicialização (veja o log do G1ArmController); posturas só no log")
        finally:
            self._busy.release()

    @staticmethod
    def _parse(request: Rotina.Goal) -> tuple[str, list[dict[str, str]], bool]:
        pessoa = request.pessoa.strip()
        if not pessoa:
            raise ReactionConfigError("rotina sem pessoa")
        voz = request.voz is True
        return pessoa, validate_steps(pessoa, json.loads(request.passos_json), exigir_a_vontade=not voz), voz

    def _on_goal(self, request: Rotina.Goal) -> GoalResponse:
        try:
            pessoa, _, voz = self._parse(request)
        except (ValueError, TypeError, ReactionConfigError) as exc:  # JSONDecodeError é ValueError
            self._publish(f"rotina rejeitada (mensagem inválida): {exc}")
            return GoalResponse.REJECT
        if self._stop.is_set():
            return GoalResponse.REJECT
        if not self._busy.acquire(blocking=False):  # solto no fim do _execute
            self._publish(f"rotina de {pessoa} rejeitada: ocupado")
            return GoalResponse.REJECT
        if not voz and self._mantida is not None:  # só a voz mexe com uma posição mantida
            self._busy.release()
            self._publish(f"rotina de {pessoa} rejeitada: posicao mantida")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _on_cancel(self, goal_handle: object) -> CancelResponse:
        self._interromper.set()
        self._parar()  # andar para na hora; uma postura em andamento termina
        return CancelResponse.ACCEPT

    def _parar(self) -> None:
        if self._ready:
            self._body.stop()

    def _on_detections(self, msg: Detection2DArray) -> None:
        agora = time.monotonic()
        caixas = [(d.results[0].id, d.bbox.center.x, d.bbox.size_y) for d in msg.detections if d.results]
        for nome in {c[0] for c in caixas}:
            self._vistos[nome] = (escolher_caixa(caixas, nome), agora)

    def _aproximar(self, pessoa: str, log: Callable[[str], None]) -> str:
        """Vira (e anda, com `aproximar`) até a pessoa. Devolve PRONTO, um DESISTIU_* ou "interrompida".

        Velocidade só armado e inicializado; desarmado só mede por MEDIR_DESARMADO_S e dá como feito.
        """
        aproximar = "aproximar" in self._estagios
        etapa = "aproximar" if aproximar else "virar"
        mover = self._ready
        cfg = self._approach
        inicio = time.monotonic()
        try:
            while not self._interromper.is_set():
                agora = time.monotonic()
                if not mover and agora - inicio >= MEDIR_DESARMADO_S:
                    return PRONTO
                caixa, visto_em = self._vistos.get(pessoa, (None, inicio))
                cmd = passo_aproximacao(cfg, aproximar, caixa, visto_em, inicio, agora)
                if caixa is None:
                    log(f"{etapa}: sem rosto ({cmd.estado})")
                else:
                    meia = cfg.largura_imagem / 2
                    log(
                        f"{etapa}: desvio={(caixa[0] - meia) / meia:+.2f} caixa={caixa[1]:.0f}px "
                        f"vx={cmd.vx:.2f} vyaw={cmd.vyaw:.2f} ({cmd.estado})"
                    )
                if mover:
                    if cmd.estado in (PRONTO, DESISTIU_ROSTO, DESISTIU_TEMPO):
                        return cmd.estado
                    self._body.velocity(cmd.vx, cmd.vyaw)
                self._interromper.wait(PASSO_APROXIMACAO_S)
            return "interrompida"
        finally:
            if mover:
                self._body.stop()

    def _execute(self, goal_handle: object) -> Rotina.Result:
        self._idle.clear()
        if not self._stop.is_set():
            self._interromper.clear()
        try:
            pessoa, passos, voz = self._parse(goal_handle.request)
            mensagem = ""
            self._publicar_corpo("rotina")

            def log(text: str) -> None:
                self._publish(text)
                try:
                    goal_handle.publish_feedback(Rotina.Feedback(passo=text))
                except Exception:  # Ctrl+C: o status no log basta
                    pass

            self._publish(f"rotina de {pessoa}: início")
            estado = PRONTO if voz or "virar" not in self._estagios else self._aproximar(pessoa, log)
            if voz:  # nunca aproxima, filtra estágios nem faz meia-volta
                ok = self._executar_voz(passos, log)
                fim = "fim" if ok else "interrompida" if self._interromper.is_set() else "falhou"
            elif estado == PRONTO:
                ok = run_routine(
                    filter_steps(passos, self._estagios),
                    postura=self._posture,
                    falar=self._speak,
                    pausa_s=self._pausa_s,
                    log=log,
                    deve_parar=self._interromper.is_set,
                    sleep=self._interromper.wait,
                )
                interrompida = not ok and self._interromper.is_set()
                fim = "fim" if ok else "interrompida" if interrompida else "falhou"
                if ok and "meia_volta" in self._estagios and not self._interromper.is_set():
                    mensagem = self._fazer_meia_volta(log)
            else:  # desistiu ou interrompida na aproximação: não cumprimenta
                ok, fim = False, estado
                if estado == DESISTIU_ROSTO and self._avisos_voz:
                    try:  # já parado; só nesse caso, para o robô não ficar narrando o que faz
                        self._speak(f"Perdi {nome_falado(pessoa)} de vista")
                    except Exception as exc:
                        log(f"fala falhou: {exc!r}")
            self._publish(f"rotina de {pessoa}: {fim}")
            try:
                if goal_handle.is_cancel_requested:  # nunca succeed() num goal em cancelamento
                    goal_handle.canceled()
                elif ok:
                    goal_handle.succeed()
                else:
                    goal_handle.abort()
            except Exception:  # Ctrl+C no meio: ninguém espera mais o resultado
                pass
            return Rotina.Result(sucesso=ok, mensagem=mensagem if ok else fim)
        finally:
            self._publicar_corpo(self._estado_corpo())
            self._idle.set()
            self._busy.release()

    def _executar_voz(self, passos: list[dict], log: Callable[[str], None]) -> bool:
        """Comando de voz: vai da posição mantida até os passos.

        A posição guardada segue o que as posturas fizeram, em qualquer saída: uma postura que
        falha deixa os braços talvez no meio do caminho (vale ela), exceto a_vontade que falhou
        (nada mudou).
        """
        mantida = self._mantida

        def postura(nome: str) -> bool:
            nonlocal mantida
            try:
                ok = self._posture(nome)
            except Exception as exc:
                log(f"postura {nome} falhou: {exc!r}")
                ok = False
            if ok:
                mantida = None if nome == A_VONTADE else nome
            elif nome != A_VONTADE:
                mantida = nome
            return ok

        try:
            return run_routine(
                transicao(self._mantida, passos),
                postura=postura,
                falar=self._speak,
                pausa_s=self._pausa_s,
                log=log,
                deve_parar=self._interromper.is_set,
                sleep=self._interromper.wait,
            )
        finally:
            self._mantida = mantida
            self._mantida_desde = time.monotonic()

    def _fazer_meia_volta(self, log: Callable[[str], None]) -> str:
        """Meia-volta à esquerda + passo curto. Devolve a mensagem do resultado (nunca falha a rotina)."""
        if not self._ready:
            self._publish("dry_run meia_volta")
            return "meia_volta: dry_run"
        log("meia_volta: girando")
        try:
            ok, erro = self._body.meia_volta(asdict(self._meia_volta), self._interromper.is_set)
        except Exception as exc:
            ok, erro = False, repr(exc)
        if not ok and self._interromper.is_set():
            erro = "interrompida"
        texto = "meia_volta: fim" if ok else f"meia_volta: falhou ({erro})"
        log(texto)
        return texto

    def _posture(self, nome: str) -> bool:
        if not self._ready:
            self._publish(f"dry_run postura {nome}")
            return True
        return self._body.posture(nome)

    def destroy_node(self) -> None:
        self._server.destroy()  # antes do nó: no Foxy, o __del__ dela depois reclama do nó destruído
        super().destroy_node()

    def shutdown(self, timeout_s: float = ESPERA_ROTINA_S) -> None:
        """Ctrl+C: interrompe a rotina depois do passo atual, devolve os braços e solta o arm_sdk."""
        self._stop.set()
        self._interromper.set()
        self._parar()  # antes de esperar qualquer coisa: depois do shutdown o body_worker não lê mais
        log = self.get_logger()
        if self._init_thread is not None and self._init_thread.is_alive():
            log.info("esperando a inicialização terminar antes de soltar os braços...")
            self._init_thread.join(INICIALIZACAO_TIMEOUT_S + ESPERA_PROCESSO_S)
        if not self._idle.is_set():
            log.info("esperando o passo atual terminar e o a_vontade antes de soltar os braços...")
            if not self._idle.wait(timeout_s):
                log.error(f"a rotina não terminou em {timeout_s:.0f} s; soltando os braços mesmo assim")
        if self._body is not None:
            log.info("devolvendo os braços ao equilíbrio e soltando o arm_sdk...")
            try:
                self._body.shutdown()
            except Exception as exc:
                log.error(f"falha ao soltar os braços: {exc!r}; use F1+RIGHT no controle")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    # Vários threads: a rotina roda no callback da ação e o nó continua recusando outras.
    executor = MultiThreadedExecutor()
    try:
        node = BodyNode()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        # O `ros2 launch` repassa o Ctrl+C como um segundo SIGINT: sem isto ele interromperia a
        # devolução dos braços no meio.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if node is not None:
            node.shutdown()
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
