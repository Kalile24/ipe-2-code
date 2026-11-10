from __future__ import annotations

import functools
import json
import os
import queue
import socket
import threading
import time

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from core.comandos_voz import PORTA_VOZ, carregar_comandos, gramatica, reconhecer
from core import discurso
from core.gravador import Gravador
from core.piper_voice import DEFAULT_URL, say
from core.vosk_voice import MODELO_PADRAO, Transcritor
from robot_reaction_interfaces.action import Rotina

DISCURSO = "discurso"
ESPERA_RESULTADO_S = 330.0  # pior caso de uma rotina no body_node (ESPERA_ROTINA_S 310) com folga


def sem_transcricao(pcm: bytes) -> str:
    raise RuntimeError("transcricao nao configurada")


class VozNode(Node):
    """Do aperto de falar do controle (UDP em 127.0.0.1) à ação /reaction/rotina.

    Datagramas: falar_inicio, falar_fim, comando:<nome>, texto:<frase>. Um ciclo por vez
    (gravar -> transcrever -> reconhecer -> rotina ou fala) numa thread própria. Recusa é
    silenciosa: só /voz/estado com `recusado`. O áudio fica na memória.
    """

    def __init__(self, gravador_factory=Gravador, transcrever=None, speak=say) -> None:
        super().__init__("voz_node")
        self.declare_parameter("dispositivo", "default")
        self.declare_parameter("comandos_file", "")
        self.declare_parameter("porta", PORTA_VOZ)
        self.declare_parameter("gravacao_max_s", 8.0)  # 5 s cortava o "apresentar... arma" com a pausa militar
        self.declare_parameter("tts_url", DEFAULT_URL)
        self.declare_parameter("tts_timeout_s", 60.0)
        self.declare_parameter("modelo_vosk", MODELO_PADRAO)
        self._gravador_factory = gravador_factory
        self._dispositivo = self.get_parameter("dispositivo").value
        self._max_s = float(self.get_parameter("gravacao_max_s").value)
        self._speak = functools.partial(
            speak, url=self.get_parameter("tts_url").value, timeout_s=float(self.get_parameter("tts_timeout_s").value)
        ) if speak is say else speak
        caminho = self.get_parameter("comandos_file").value or os.path.join(
            get_package_share_directory("robot_reaction_ros"), "config", "comandos_voz.yaml"
        )
        with open(caminho, encoding="utf-8") as f:
            self._tabela = carregar_comandos(yaml.safe_load(f))
        self._transcrever = transcrever or self._criar_transcritor()

        self._rotina = ActionClient(self, Rotina, "/reaction/rotina")
        self._estado_pub = self.create_publisher(
            String, "/voz/estado", QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )
        self._corpo = "livre"
        self.create_subscription(
            String, "/reaction/corpo", self._on_corpo, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )
        self._lock = threading.Lock()
        self._ocupado = False  # ciclo em andamento: do aperto até o resultado da ação ou o fim da fala
        self._gravador = None
        self._timer: threading.Timer | None = None
        self._ciclo: threading.Thread | None = None
        self._microfone = bool(self._gravador_factory(self._dispositivo).presente())  # reavaliado a cada aperto
        self._estado = {"texto": "", "comando": "", "resultado": "", "transcricao_s": 0.0, "microfone": self._microfone}

        self._pendentes: queue.Queue = queue.Queue()  # goals a enviar pelo executor (ActionClient do Foxy não tem lock)
        self.create_timer(0.02, self._drenar)
        self._parar = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", int(self.get_parameter("porta").value)))
        self._sock.settimeout(0.5)
        self._udp = threading.Thread(target=self._ouvir, daemon=True)
        self._udp.start()
        self._publicar("")  # o painel avisa de microfone ausente já na subida
        self.get_logger().info(f"voz: UDP em 127.0.0.1:{self._sock.getsockname()[1]}, microfone {self._dispositivo}")

    def _criar_transcritor(self):
        """Vosk com a gramática dos comandos; sem ele o nó sobe assim mesmo e responde "não entendi"."""
        try:
            t = Transcritor(gramatica(self._tabela), modelo=self.get_parameter("modelo_vosk").value)
        except Exception as exc:
            self.get_logger().error(f"reconhecimento de fala desligado: {exc}")
            return sem_transcricao
        self.get_logger().info(f"reconhecimento de fala: Vosk, {len(self._tabela.frases)} frases")
        return t

    def _on_corpo(self, msg: String) -> None:
        self._corpo = msg.data

    def _ouvir(self) -> None:
        while not self._parar.is_set():
            try:
                dados, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                self._on_datagrama(dados.decode("utf-8", "replace").strip())
            except Exception as exc:  # um datagrama ruim não derruba a escuta
                self.get_logger().error(f"datagrama: {exc!r}")

    def _publicar(self, resultado: str, **campos: object) -> None:
        self._estado.update(campos, resultado=resultado, microfone=self._microfone)
        self._estado_pub.publish(String(data=json.dumps(self._estado, ensure_ascii=False)))

    def _on_datagrama(self, msg: str) -> None:
        if msg == "falar_inicio":
            self._falar_inicio()
        elif msg == "falar_fim":
            self._fim_gravacao()
        elif msg.startswith("comando:"):
            nome = msg[len("comando:"):]
            if nome == DISCURSO:  # a fala de apresentação (F3+R1, painel): texto de data/discurso.txt
                self._iniciar_ciclo(self._executar, nome, "")
            elif nome not in self._tabela.comandos:
                self.get_logger().warn(f"comando desconhecido: {nome!r}")
            elif nome == "a_vontade":
                # sempre passa (some o ciclo em andamento); o body_node é quem recusa o que sobrar
                if self._corpo == "rotina":
                    self._publicar("recusado", comando=nome)
                else:
                    self._despachar(nome, lambda ok: self._publicar("ok" if ok else "recusado", comando=nome))
            else:
                self._iniciar_ciclo(self._executar, nome, "")
        elif msg.startswith("texto:"):
            self._iniciar_ciclo(self._reconhecer_e_executar, msg[len("texto:"):])
        else:
            self.get_logger().warn(f"datagrama desconhecido: {msg!r}")

    def _iniciar_ciclo(self, alvo, *args) -> bool:
        """Reserva o ciclo e roda `alvo` numa thread; False (e `recusado`) se já há um."""
        with self._lock:
            if self._ocupado:
                self._publicar("recusado")
                return False
            self._ocupado = True
        self._ciclo = threading.Thread(target=self._rodar, args=(alvo, args), daemon=True)
        self._ciclo.start()
        return True

    def _rodar(self, alvo, args) -> None:
        try:
            alvo(*args)
        except Exception as exc:
            self.get_logger().error(f"ciclo de voz: {exc!r}")
        finally:
            self._ocupado = False

    def _falar_inicio(self) -> None:
        with self._lock:
            if self._ocupado or self._corpo == "rotina":
                self._publicar("recusado")
                return
            self._ocupado = True
        g = self._gravador_factory(self._dispositivo)
        self._microfone = bool(g.presente())  # uma vez por aperto
        try:
            g.iniciar()
        except Exception as exc:  # OSError (sem arecord, saiu na partida) ou qualquer outra: nunca fica surdo
            self.get_logger().warn(f"microfone: {exc!r}")
            self._microfone = False
            self._ocupado = False
            self._publicar("recusado")
            return
        with self._lock:
            self._gravador = g
            self._timer = threading.Timer(self._max_s, self._fim_gravacao)
            self._timer.daemon = True
            self._timer.start()
        self._publicar("gravando", texto="", comando="", transcricao_s=0.0)

    def _fim_gravacao(self) -> None:
        # falar_fim e o limite disputam: só o primeiro leva o gravador
        with self._lock:
            g, self._gravador = self._gravador, None
            if g is None:
                return
            if self._timer is not None:
                self._timer.cancel()
        self._ciclo = threading.Thread(target=self._rodar, args=(self._transcrever_e_executar, (g,)), daemon=True)
        self._ciclo.start()

    def _transcrever_e_executar(self, g) -> None:
        pcm = g.parar()
        self._publicar("transcrevendo")
        t0 = time.monotonic()
        try:
            texto = self._transcrever(pcm)
        except Exception as exc:
            self.get_logger().warn(f"transcricao falhou: {exc!r}")
            texto = ""
        self._reconhecer_e_executar(texto, time.monotonic() - t0)

    def _reconhecer_e_executar(self, texto: str, transcricao_s: float = 0.0) -> None:
        nome = reconhecer(self._tabela, texto) if texto else None
        self.get_logger().info(f"voz: {texto!r} -> {nome}")
        self._executar(nome, texto, transcricao_s)

    def _executar(self, nome: str | None, texto: str, transcricao_s: float = 0.0) -> None:
        if nome is None:
            if self._corpo == "rotina":
                self._publicar("recusado", texto=texto, comando="", transcricao_s=transcricao_s)
                return
            self._publicar("nao_entendi", texto=texto, comando="", transcricao_s=transcricao_s)
            self._dizer(self._tabela.nao_entendi)
            return
        fim = threading.Event()
        resultado = []

        def feito(ok: bool) -> None:
            resultado.append(ok)
            fim.set()

        if not self._despachar(nome, feito):
            self._publicar("recusado", texto=texto, comando=nome, transcricao_s=transcricao_s)
            return
        fim.wait(ESPERA_RESULTADO_S)
        ok = bool(resultado and resultado[0])
        self._publicar("ok" if ok else "recusado", texto=texto, comando=nome, transcricao_s=transcricao_s)

    def _despachar(self, nome: str, feito) -> bool:
        """Enfileira o goal do comando; `feito(sucesso)` roda no executor. False se o body_node não está de pé."""
        if not self._rotina.server_is_ready():
            self.get_logger().warn("o body_node não está de pé")
            return False
        passos = discurso.passos(discurso.ler()) if nome == DISCURSO else self._tabela.comandos[nome][1]
        goal = Rotina.Goal(pessoa="voz", passos_json=json.dumps(passos, ensure_ascii=False), voz=True)
        self._pendentes.put((goal, feito))
        return True

    def _drenar(self) -> None:
        """No executor: manda os goals pendentes (o ActionClient não é seguro entre threads)."""
        while True:
            try:
                goal, feito = self._pendentes.get_nowait()
            except queue.Empty:
                return

            def on_goal(future, feito=feito) -> None:
                handle = future.result()
                if not handle.accepted:
                    feito(False)
                    return
                handle.get_result_async().add_done_callback(lambda f: feito(bool(f.result().result.sucesso)))

            self._rotina.send_goal_async(goal).add_done_callback(on_goal)

    def _dizer(self, texto: str) -> None:
        try:
            self._speak(texto)
        except Exception as exc:
            self.get_logger().warn(f"fala falhou: {exc!r}")

    def destroy_node(self) -> None:
        self._parar.set()
        self._sock.close()
        self._udp.join(2.0)
        with self._lock:
            g, self._gravador = self._gravador, None
            if self._timer is not None:
                self._timer.cancel()
        if g is not None:
            g.parar()
        self._rotina.destroy()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = VozNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
