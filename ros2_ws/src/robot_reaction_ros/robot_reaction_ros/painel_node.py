"""Painel web de monitoramento e operação do robô: http://<ip do robô>:8080 (hotspot: 10.42.0.1).

Mostra câmera, reconhecimento (quem está na frente e a altura da caixa), o estágio do robô
(/reaction/rotina_status), armado/desarmado e as reações automáticas; tem os mesmos comandos do
controle (subir, cumprimentar agora, ligar/desligar automático, parar), o formulário do
data/operacao.yaml e o cadastro de uma pessoa por foto (serviço ~/cadastrar do face_recognition_node).

Só biblioteca padrão + rclpy (nada novo no Jetson). Sobe à parte da rotina (scripts/systemd/
ipe-painel.service), para mostrar também "rotina parada". Sem login: a proteção é a senha do hotspot.
Spec: docs/superpowers/specs/2026-11-04-painel-design.md
"""
from __future__ import annotations

import array
import base64
import json
import os
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import Parameter as ParameterMsg
from rcl_interfaces.msg import ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.reaction_policy import load_reactions
from robot_reaction_interfaces.srv import Cadastrar

REPO = os.path.expanduser(os.environ.get("IPE_REPO", "~/ipe-2-code"))
SESSAO = "rotina"
RECENTE_S = 2.0  # câmera/detecção mais velha que isso conta como parada
CAMPOS_OPERACAO = (  # o que o formulário pode mudar no operacao.yaml (o resto fica como está)
    "estagios", "altura_caixa_alvo_px", "vx", "vyaw_max", "kp_giro", "inverter_giro", "centro_ok",
    "centro_para_andar", "perda_rosto_s", "desistir_s", "tempo_max_s",
)
FIM = ("fim", "falhou", "interrompida", "desistiu", "rejeitada")


def estagio(status: str) -> str:
    """O estágio do robô a partir da última linha do /reaction/rotina_status."""
    for prefixo, nome in (("aproximar:", "aproximando"), ("virar:", "virando"), ("inicializando", "inicializando"),
                          ("pronto", "pronto"), ("desarmado", "pronto (desarmado)"), ("falha na inicialização", "falha na inicialização")):
        if status.startswith(prefixo):
            return nome
    if status.startswith("rotina de") and any(f in status for f in FIM):
        return "pronto (última: " + status.split(": ", 1)[-1] + ")"
    if status.startswith(("rotina de", "postura:", "fala:", "pausa:", "dry_run", "tentando")):
        return "rotina"
    return status or "—"


def sessao_de_pe() -> bool:
    try:
        return subprocess.run(["tmux", "has-session", "-t", SESSAO], capture_output=True).returncode == 0
    except FileNotFoundError:  # sem tmux, não há rotina de pé
        return False


class PainelNode(Node):
    def __init__(self) -> None:
        super().__init__("painel_node")
        self.declare_parameter("porta", 8080)
        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("operacao_file", os.path.join(REPO, "data", "operacao.yaml"))
        self._operacao_file = self.get_parameter("operacao_file").value
        self._lock = threading.Lock()
        # Não assina as imagens (30 quadros/s de 640x480 pesariam no Jetson): câmera = tem publicador
        # no image_topic; o ritmo vem das detecções (o reconhecimento publica uma por quadro).
        self._image_topic = self.get_parameter("image_topic").value
        self._quadros: deque[float] = deque(maxlen=100)
        self._deteccoes: list[dict] = []
        self._deteccao_em = 0.0
        self._status: deque[tuple[float, str]] = deque(maxlen=40)
        self.create_subscription(Detection2DArray, self.get_parameter("detections_topic").value, self._on_detections, 1)
        self.create_subscription(String, "/reaction/rotina_status", self._on_status, 20)
        self._get = self.create_client(GetParameters, "/reaction_node/get_parameters")
        self._set = self.create_client(SetParameters, "/reaction_node/set_parameters")
        self._cadastrar = self.create_client(Cadastrar, "/face_recognition_node/cadastrar")

    def _on_detections(self, msg: Detection2DArray) -> None:
        caixas = [{"nome": d.results[0].id, "nota": round(d.results[0].score, 2), "caixa_px": round(d.bbox.size_y)}
                  for d in msg.detections if d.results]
        agora = time.monotonic()
        with self._lock:
            self._deteccoes, self._deteccao_em = caixas, agora
            self._quadros.append(agora)

    def _on_status(self, msg: String) -> None:
        with self._lock:
            self._status.append((time.time(), msg.data))

    # ---- chamadas aos outros nós (do thread do HTTP; o executor gira no principal) ----------
    def _chamar(self, cliente: object, pedido: object, timeout_s: float) -> object | None:
        if not cliente.wait_for_service(timeout_sec=0.5):
            return None
        futuro = cliente.call_async(pedido)
        fim = time.monotonic() + timeout_s
        while not futuro.done() and time.monotonic() < fim:
            time.sleep(0.02)
        return futuro.result() if futuro.done() else None

    def param_reacao(self, nome: str) -> object | None:
        resposta = self._chamar(self._get, GetParameters.Request(names=[nome]), 2.0)
        if resposta is None or not resposta.values:
            return None
        v = resposta.values[0]
        return {ParameterType.PARAMETER_BOOL: v.bool_value, ParameterType.PARAMETER_STRING: v.string_value}.get(v.type)

    def set_reacao(self, nome: str, valor: object) -> str:
        if isinstance(valor, bool):
            pv = ParameterValue(type=ParameterType.PARAMETER_BOOL, bool_value=valor)
        else:
            pv = ParameterValue(type=ParameterType.PARAMETER_STRING, string_value=str(valor))
        resposta = self._chamar(self._set, SetParameters.Request(parameters=[ParameterMsg(name=nome, value=pv)]), 3.0)
        if resposta is None:
            return "reaction_node não respondeu (a rotina está de pé?)"
        r = resposta.results[0]
        return "ok" if r.successful else r.reason

    def cadastrar(self, nome: str, fotos_b64: list[str]) -> dict:
        fotos = [CompressedImage(format="jpeg", data=array.array("B", base64.b64decode(f.split(",", 1)[-1]))) for f in fotos_b64]
        resposta = self._chamar(self._cadastrar, Cadastrar.Request(nome=nome, fotos=fotos), 60.0)
        if resposta is None:
            return {"ok": False, "mensagem": "face_recognition_node não respondeu (a rotina está de pé?)"}
        return {"ok": resposta.ok, "mensagem": resposta.mensagem, "tem_rotina": nome in self.pessoas_com_rotina()}

    # ---- estado e operação ------------------------------------------------------------------
    def pessoas_com_rotina(self) -> list[str]:
        try:
            with open(os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "reactions.yaml")) as f:
                return sorted(load_reactions(yaml.safe_load(f)))
        except Exception:
            return []

    def estado(self) -> dict:
        agora = time.monotonic()
        with self._lock:
            quadros = [t for t in self._quadros if agora - t <= RECENTE_S]
            deteccoes = self._deteccoes if agora - self._deteccao_em <= RECENTE_S else []
            deteccao_viva = agora - self._deteccao_em <= RECENTE_S
            status = list(self._status)
        nos = set(self.get_node_names())
        ultimo = status[-1][1] if status else ""
        rotina = sessao_de_pe() or "body_node" in nos  # também quando o launch subiu à mão
        return {
            "rotina_de_pe": rotina,
            "camera": {"ok": self.count_publishers(self._image_topic) > 0},
            "reconhecimento": {"ok": deteccao_viva, "no": "face_recognition_node" in nos,
                               "fps": round(len(quadros) / RECENTE_S, 1)},
            "vistos": deteccoes,
            "estagio": estagio(ultimo) if rotina else "rotina parada",
            "body_node": "body_node" in nos,
            "automatico": self.param_reacao("automatico") if "reaction_node" in nos else None,
            "armado": any("pronto: em equilíbrio" in s or "inicializando" in s for _, s in status),
            "status": [{"hora": time.strftime("%H:%M:%S", time.localtime(t)), "texto": s} for t, s in status[-15:]][::-1],
            "pessoas_com_rotina": self.pessoas_com_rotina(),
        }

    def acao(self, nome: str) -> str:
        script = os.path.join(REPO, "scripts", "robo_rotina_cumprimento.sh")
        if nome in ("subir_desarmado", "subir_armado"):
            if sessao_de_pe():
                return "a rotina já está de pé"
            args = [script] + (["--controle"] if nome == "subir_armado" else [])
            subprocess.Popen(args, stdin=subprocess.DEVNULL)
            return "subindo… (acompanhe o estágio)"
        if nome == "parar":
            if not sessao_de_pe():
                return "nenhuma rotina de pé"
            subprocess.run(["tmux", "send-keys", "-t", f"{SESSAO}:rotina", "C-c"])
            return "parando"
        if nome == "agora":
            return self.set_reacao("cumprimentar_agora", "agora")
        if nome == "automatico":
            atual = self.param_reacao("automatico")
            return "reaction_node não respondeu" if atual is None else self.set_reacao("automatico", not atual)
        return f"ação desconhecida {nome!r}"

    def operacao(self) -> dict:
        caminho = self._operacao_file
        if not os.path.exists(caminho):
            caminho = os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "operacao.yaml")
        with open(caminho) as f:
            return yaml.safe_load(f)["/**"]["ros__parameters"]

    def salvar_operacao(self, novos: dict) -> str:
        atual = self.operacao()
        for campo in CAMPOS_OPERACAO:
            if campo in novos:
                tipo = type(atual[campo])
                valor = novos[campo]
                atual[campo] = (valor in (True, "true", "on", "1")) if tipo is bool else tipo(valor)
        os.makedirs(os.path.dirname(self._operacao_file), exist_ok=True)
        with open(self._operacao_file, "w") as f:
            yaml.safe_dump({"/**": {"ros__parameters": atual}}, f, allow_unicode=True, sort_keys=False)
        return f"salvo em {self._operacao_file}; vale na próxima subida da rotina"


def handler(painel: PainelNode) -> type:
    pagina = open(os.path.join(get_package_share_directory("robot_reaction_ros"), "painel", "index.html"), "rb").read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # sem uma linha por pedido no log
            pass

        def _json(self, dados: object, codigo: int = 200) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _corpo(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

        def do_GET(self) -> None:
            try:
                self._get()
            except Exception as exc:  # um pedido ruim não derruba o painel
                self._json({"mensagem": f"erro: {exc!r}"}, 500)

        def _get(self) -> None:
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(pagina)
            elif self.path == "/estado":
                self._json(painel.estado())
            elif self.path == "/operacao":
                self._json(painel.operacao())
            else:
                self._json({"erro": "não existe"}, 404)

        def do_POST(self) -> None:
            try:
                if self.path.startswith("/acao/"):
                    self._json({"mensagem": painel.acao(self.path[len("/acao/"):])})
                elif self.path == "/operacao":
                    self._json({"mensagem": painel.salvar_operacao(self._corpo())})
                elif self.path == "/cadastrar":
                    dados = self._corpo()
                    self._json(painel.cadastrar(str(dados.get("nome", "")), list(dados.get("fotos", []))))
                else:
                    self._json({"erro": "não existe"}, 404)
            except Exception as exc:  # um pedido ruim não derruba o painel
                self._json({"mensagem": f"erro: {exc!r}"}, 400)

    return Handler


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    painel = PainelNode()
    porta = int(painel.get_parameter("porta").value)
    servidor = ThreadingHTTPServer(("0.0.0.0", porta), handler(painel))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    painel.get_logger().info(f"painel em http://0.0.0.0:{porta}")
    executor = MultiThreadedExecutor()
    executor.add_node(painel)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.shutdown()
        executor.shutdown()
        painel.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
