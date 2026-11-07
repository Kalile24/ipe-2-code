from __future__ import annotations

import functools
import json
import os
import threading
import time

import rclpy
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import SetParametersResult
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.approach import DESISTIU_TEMPO
from core.config import REACOES_EXTRA
from core.pessoas import carregar_reacoes
from core.piper_voice import DEFAULT_URL, say
from core.reaction_policy import ReactionPolicy
from robot_reaction_interfaces.action import Rotina


TODOS = "todos"
DETECCAO_RECENTE_S = 1.0  # cumprimentar_agora só usa detecções com até isto de idade


class ReactionNode(Node):
    """Escuta as detecções e manda a rotina de quem a merece ao body_node (ação /reaction/rotina).

    Uma rotina por vez: enquanto ela roda, ninguém mais é cumprimentado. Se o body_node não está
    de pé ou recusa a rotina, a pessoa não conta como cumprimentada (ReactionPolicy.forget).
    Comando manual de teste: `ros2 param set /reaction_node liberar <nome|todos>`
    (scripts/robo_liberar_cumprimento.sh).
    Operador (combos do controle, scripts/robo_controle.py): `automatico` liga/desliga os
    cumprimentos sozinhos (desligado, só acompanha quem está na frente); escrever qualquer valor em
    `cumprimentar_agora` cumprimenta já a pessoa do mapa que está sendo reconhecida.
    Depois de uma rotina com meia-volta o robô fica de costas para a pessoa: não cumprimenta mais
    sozinho (só acompanha quem aparece) até o operador usar `liberar`, ligar `automatico` ou
    `cumprimentar_agora`.
    """

    def __init__(self) -> None:
        super().__init__("reaction_node")
        self.declare_parameter("reactions_file", "")
        self.declare_parameter("reactions_extra_file", REACOES_EXTRA)
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("confirm_frames", 5)
        self.declare_parameter("person_cooldown_s", 300.0)
        self.declare_parameter("global_cooldown_s", 10.0)
        self.declare_parameter("absence_s", 5.0)
        self.declare_parameter("espera_desistiu_s", 60.0)
        self.declare_parameter("liberar", "")
        self.declare_parameter("automatico", True)
        self.declare_parameter("cumprimentar_agora", "")
        self.declare_parameter("tts_url", DEFAULT_URL)
        self.declare_parameter("tts_timeout_s", 60.0)
        self._automatico = self.get_parameter("automatico").value is True
        self._say = functools.partial(
            say, url=self.get_parameter("tts_url").value, timeout_s=float(self.get_parameter("tts_timeout_s").value)
        )
        self._visto: list[tuple[str, float]] = []  # última detecção (nome, nota) e quando chegou
        self._visto_em = float("-inf")

        path = self.get_parameter("reactions_file").value or os.path.join(
            get_package_share_directory("robot_reaction_ros"), "config", "reactions.yaml"
        )
        # Arquivo do pacote ausente ou inválido derruba o nó na partida; o de pessoas extras, não.
        reactions, aviso = carregar_reacoes(path, self.get_parameter("reactions_extra_file").value)
        if aviso:
            self.get_logger().warn(aviso)
        # float()/int(): `-p x:=60` chega como int e `-p x:=5.0` como float
        self._policy = ReactionPolicy(
            reactions,
            confirm_frames=int(self.get_parameter("confirm_frames").value),
            person_cooldown_s=float(self.get_parameter("person_cooldown_s").value),
            global_cooldown_s=float(self.get_parameter("global_cooldown_s").value),
            absence_s=float(self.get_parameter("absence_s").value),
            espera_desistiu_s=float(self.get_parameter("espera_desistiu_s").value),
        )

        detections_topic = self.get_parameter("detections_topic").value
        self._rotina = ActionClient(self, Rotina, "/reaction/rotina")
        self._em_andamento: str | None = None  # pessoa cuja rotina o body_node está executando
        self._aguardando_operador = False  # meia-volta feita: só o operador libera os cumprimentos
        self._status_pub = self.create_publisher(String, "/reaction/rotina_status", 10)
        self._subscription = self.create_subscription(
            Detection2DArray, detections_topic, self._on_detections, QoSProfile(depth=1)
        )
        self.add_on_set_parameters_callback(self._on_set_parameters)
        self.get_logger().info(f"mapa {path}: {reactions}; assinando {detections_topic}")

    def _falar(self, texto: str) -> None:
        """Confirmação para o operador pela caixa, sem segurar o callback; sem caixa, só o log."""
        self.get_logger().info(f"fala: {texto}")

        def falar() -> None:
            try:
                self._say(texto)
            except Exception as exc:
                self.get_logger().warn(f"fala falhou: {exc!r}")

        threading.Thread(target=falar, daemon=True).start()

    def _fim_da_espera(self) -> None:
        if self._aguardando_operador:
            self._aguardando_operador = False
            self._status_pub.publish(String(data="pronto: cumprimentos liberados"))

    def _on_set_parameters(self, params: list) -> SetParametersResult:
        for p in params:
            if p.name == "automatico":
                self._automatico = p.value is True
                if self._automatico:
                    self._fim_da_espera()
                self._falar(f"Reações automáticas {'ligadas' if self._automatico else 'desligadas'}.")
                continue
            if p.name == "cumprimentar_agora":
                if self._em_andamento is not None:
                    return SetParametersResult(successful=False, reason=f"rotina em andamento ({self._em_andamento})")
                agora = time.monotonic()
                seen = self._visto if agora - self._visto_em <= DETECCAO_RECENTE_S else []
                hit = self._policy.now(seen, agora)
                if hit is None:
                    self._falar("Não reconheço ninguém.")
                else:
                    self._fim_da_espera()
                    self._enviar(*hit)
                continue
            if p.name != "liberar":
                continue
            nome = str(p.value).strip()
            try:
                self._policy.release(None if nome in ("", TODOS) else nome)
            except KeyError as exc:
                return SetParametersResult(successful=False, reason=str(exc))
            self._fim_da_espera()
            self.get_logger().info(f"liberado: {nome or TODOS} pode ser cumprimentado de novo")
        return SetParametersResult(successful=True)

    def _on_detections(self, msg: Detection2DArray) -> None:
        seen = [(d.results[0].id, d.results[0].score) for d in msg.detections if d.results]
        self._visto, self._visto_em = seen, time.monotonic()
        if self._em_andamento is not None and not self._rotina.server_is_ready():
            # body_node morreu no meio: o resultado nunca vai chegar
            self.get_logger().warn(f"rotina de {self._em_andamento}: o body_node sumiu")
            self._em_andamento = None
        livre = self._automatico and self._em_andamento is None and not self._aguardando_operador
        hit = self._policy.update(seen, time.monotonic(), allow_fire=livre)
        if hit is not None:
            self._enviar(*hit)

    def _enviar(self, nome: str, reacao: list[dict[str, str]]) -> None:
        log = self.get_logger()
        if not self._rotina.server_is_ready():
            log.warn(f"{nome}: o body_node não está de pé; não cumprimentado")
            self._policy.forget(nome)
            return
        log.info(f"reagindo a {nome}: rotina de {len(reacao)} passos")
        self._em_andamento = nome
        goal = Rotina.Goal(pessoa=nome, passos_json=json.dumps(reacao, ensure_ascii=False))
        self._rotina.send_goal_async(goal).add_done_callback(lambda future: self._on_goal_response(nome, future))

    def destroy_node(self) -> None:
        self._rotina.destroy()  # antes do nó: no Foxy, o __del__ dele depois reclama do nó destruído
        super().destroy_node()

    def _on_goal_response(self, nome: str, future: object) -> None:
        handle = future.result()
        if self._em_andamento != nome:  # já dado como perdido (body_node sumiu)
            return
        if not handle.accepted:  # inicializando, ocupado ou encerrando: o motivo está no rotina_status
            self.get_logger().warn(f"{nome}: o body_node recusou a rotina; não cumprimentado")
            self._policy.forget(nome)
            self._em_andamento = None
            return
        handle.get_result_async().add_done_callback(lambda future: self._on_result(nome, future))

    def _on_result(self, nome: str, future: object) -> None:
        # Rotina que falhou no meio também conta como cumprimento: repetir não consertaria o braço.
        resultado = future.result().result
        self.get_logger().info(f"rotina de {nome}: {'fim' if resultado.sucesso else resultado.mensagem}")
        if not resultado.sucesso and resultado.mensagem.startswith("desistiu"):
            # A aproximação desistiu: não cumprimentou, então não conta para os 5 min. Rosto perdido:
            # tenta assim que reconhecer de novo. Tempo esgotado: espera, para não andar até a
            # pessoa sem parar.
            if resultado.mensagem == DESISTIU_TEMPO:
                self._policy.desistiu(nome, time.monotonic())
            else:
                self._policy.forget(nome)
        self._em_andamento = None
        if resultado.sucesso and resultado.mensagem.startswith("meia_volta"):
            # De costas para a pessoa: não cumprimenta de novo até o operador liberar.
            self._aguardando_operador = True
            self._status_pub.publish(String(data="aguardando o operador (Liberar cumprimentos)"))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = ReactionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
