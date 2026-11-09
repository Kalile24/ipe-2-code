"""Painel web de monitoramento e operação do robô: http://<ip do robô>:8080 (hotspot: 10.42.0.1).

Mostra câmera, reconhecimento (quem está na frente e a altura da caixa), o estágio do robô
(/reaction/rotina_status), armado/desarmado e as reações automáticas; tem os mesmos comandos do
controle (subir, cumprimentar agora, ligar/desligar automático, parar), o formulário do
data/operacao.yaml e o cadastro de uma pessoa por foto (serviço ~/cadastrar do face_recognition_node).

Só biblioteca padrão + rclpy (nada novo no Jetson). Sobe à parte da rotina (scripts/systemd/
ipe-painel.service), para mostrar também "rotina parada". Sem login: escuta em todas as redes do robô,
então quem estiver numa delas consegue comandar (só pedidos de outro site são recusados). No hotspot,
a proteção é a senha dele; em outro Wi-Fi, não há proteção: use em rede de confiança.
Spec: docs/superpowers/specs/2026-11-04-painel-design.md
"""
from __future__ import annotations

import array
import base64
import glob
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import Parameter as ParameterMsg
from rcl_interfaces.msg import ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.approach import LIMITES_OPERACAO, validar_operacao
from core.bipes import tocar
from core.caixa import CAIXA_PADRAO, caixa_atual, ler_dispositivos, mac_valido, nome_do_sink
from core.comandos_voz import enviar_voz
from core.config import DB_PATH, MODEL_NAME
from core.identity_store import IdentityStore
from core.pessoas import carregar_reacoes, nome_falado, rotina_padrao
from core.reaction_policy import load_reactions
from core.stages import migrar_estagios, parse_stages
from robot_reaction_interfaces.srv import Cadastrar

REPO = os.path.expanduser(os.environ.get("IPE_REPO", "~/ipe-2-code"))
SESSAO = "rotina"
RECENTE_S = 2.0  # câmera/detecção mais velha que isso conta como parada
CAMPOS_OPERACAO = (  # o que o formulário pode mudar no operacao.yaml (o resto fica como está)
    "estagios", "altura_caixa_alvo_px", "vx", "vyaw_max", "vyaw_min", "kp_giro", "inverter_giro", "centro_ok",
    "centro_para_andar", "centro_chegada", "perda_rosto_s", "desistir_s", "tempo_max_s", "avisos_voz",
    "vyaw_meia_volta", "tolerancia_meia_volta_graus", "passo_m", "vx_passo", "tempo_max_meia_volta_s",
)
FIM = ("fim", "falhou", "interrompida", "desistiu", "rejeitada")
WEBCAM_GLOB = "/dev/v4l/by-id/*-video-index0"  # o mesmo que o robo_rotina_cumprimento.sh usa
ARQ_CAIXA = os.path.join(REPO, "data", "caixa.txt")
ARQ_REACOES = os.path.join(REPO, "data", "reactions.yaml")
DB_BASE = DB_PATH
NOME_VALIDO = re.compile(r"^[a-z0-9_]+$")
CAIXA_CACHE_S = 3.0  # bluetoothctl/pactl a cada pedido pesariam no painel
FORMATO_CACHE_S = 5.0
PARAM_RETRY_S = 10.0  # nó que não respondeu um parâmetro fixo: só pergunta de novo depois disso
FOTOS_MAX = 10
CORPO_MAX = 64 * 1024 * 1024  # 10 fotos de 1280 px cabem com folga
EVENTOS_NA_TELA = 30
ORDENS = {"sentido": "sentido", "continencia": "continência", "apresentacao": "apresentação", "a_vontade": "à vontade"}  # nomes de config/comandos_voz.yaml


def registrar_status(status: deque, texto: str, agora: float) -> None:
    """Acrescenta uma linha de status como [hora, texto, repetições].

    A aproximação publica ~10 linhas/s: sem juntar, 40 linhas não chegavam a 4 s de histórico. Junta
    as seguidas da mesma etapa e do mesmo estado; uma mudança (andando → sem_rosto) abre outra linha.
    """
    etapa = texto.split(":", 1)[0]
    if etapa in ("aproximar", "virar") and status:
        ultimo = status[-1]
        if ultimo[1].split(":", 1)[0] == etapa and ultimo[1].rsplit("(", 1)[-1] == texto.rsplit("(", 1)[-1]:
            ultimo[0], ultimo[1], ultimo[2] = agora, texto, ultimo[2] + 1
            return
    status.append([agora, texto, 1])


def valor_param(v: object) -> object | None:
    """O valor de um rcl_interfaces/ParameterValue, ou None se o tipo não é um dos usados aqui."""
    return {ParameterType.PARAMETER_BOOL: v.bool_value, ParameterType.PARAMETER_STRING: v.string_value,
            ParameterType.PARAMETER_DOUBLE: v.double_value, ParameterType.PARAMETER_INTEGER: v.integer_value}.get(v.type)


def _comando(*args: str, timeout: float = 25.0) -> str:
    """Saída do comando; vazia se ele não existe ou passou do tempo (quem chama confere o resultado)."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def caixa_de_som(mac: str) -> dict:
    """Caixa conectada pelo Bluetooth? E é a saída de som padrão (por onde saem fala e bipes)?"""
    try:
        info = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=3).stdout
        padrao = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=3).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"conectada": None, "saida_padrao": None, "mac": mac, "padrao": mac == CAIXA_PADRAO}
    return {"conectada": "Connected: yes" in info, "saida_padrao": nome_do_sink(mac) in padrao,
            "mac": mac, "padrao": mac == CAIXA_PADRAO}


def webcam_usb() -> float | None:
    """Quando a webcam USB (não a RealSense) apareceu pela última vez, ou None se não está conectada.

    O link em /dev/v4l/by-id é recriado a cada reconexão: a hora dele é a da última reconexão.
    """
    for caminho in sorted(glob.glob(WEBCAM_GLOB)):
        if "RealSense" in caminho:
            continue
        try:
            return os.lstat(caminho).st_mtime
        except OSError:  # sumiu entre o glob e o lstat
            continue
    return None


def webcam_nome() -> str | None:
    """O nome da webcam USB conectada, como o sistema a chama: confirma qual câmera está em uso."""
    for caminho in sorted(glob.glob(WEBCAM_GLOB)):
        if "RealSense" not in caminho:
            nome = os.path.basename(caminho)
            return nome[len("usb-"):-len("-video-index0")].replace("_", " ") if nome.startswith("usb-") else nome
    return None


def ler_formato_webcam(fmt: str, parm: str) -> dict | None:
    """Tamanho e quadros/s reais, das saídas de `v4l2-ctl --get-fmt-video` e `--get-parm`.

    O driver pode entregar outra coisa que não a pedida no launch (a Intelbras ignora os 15 q/s).
    """
    tamanho = re.search(r"Width/Height\s*:\s*(\d+)/(\d+)", fmt)
    if not tamanho:
        return None
    fps = re.search(r"Frames per second:\s*([\d.]+)", parm)
    return {"largura": int(tamanho[1]), "altura": int(tamanho[2]), "fps": round(float(fps[1])) if fps else None}


def fechar_sessao_quando_terminar(espera_s: float = 90.0) -> None:
    """Espera a janela 'rotina' voltar ao bash (o launch saiu) e fecha a sessão; se não sair a tempo,
    deixa como está (fechar no meio mataria o body_worker com o arm_sdk ativo)."""
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim:
        saida = subprocess.run(["tmux", "display-message", "-p", "-t", f"{SESSAO}:rotina", "#{pane_current_command}"],
                               capture_output=True, text=True)
        if saida.returncode != 0:
            return  # a sessão já não existe
        if saida.stdout.strip() in ("bash", "sh"):
            subprocess.run(["tmux", "kill-session", "-t", SESSAO])
            return
        time.sleep(0.5)


def sessao_criada() -> float | None:
    """Hora em que a sessão tmux da rotina subiu, ou None se ela não está de pé."""
    try:
        saida = subprocess.run(["tmux", "display-message", "-p", "-t", SESSAO, "#{session_created}"],
                               capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return float(saida.stdout) if saida.returncode == 0 and saida.stdout.strip().isdigit() else None


def estagio(status: str) -> str:
    """O estágio do robô a partir da última linha do /reaction/rotina_status."""
    if status.startswith(("meia_volta:", "dry_run meia_volta")) and "fim" not in status and "falhou" not in status:
        return "fazendo meia-volta"
    for prefixo, nome in (("aguardando o operador", "aguardando o operador"), ("aproximar:", "aproximando"), ("virar:", "virando"), ("inicializando", "inicializando"),
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
        self._status: deque[list] = deque(maxlen=200)  # [hora, texto, repetições]: registrar_status
        self._armado: bool | None = None  # o que o body_node anunciou; None = ainda não se sabe
        self._params: dict[str, tuple[object, float]] = {}  # nó → (parâmetro fixo, quando perguntou)
        self._subindo = threading.Event()
        self._parando = threading.Event()
        self._subida_erro: str | None = None
        self._operacao_alterada_em = 0.0
        self._webcam_vista: float | None = webcam_usb()  # última hora de conexão observada
        self._webcam_quedas = 0  # desconexões/reconexões vistas desde que o painel subiu
        self._caixa: tuple[float, dict] = (0.0, {})  # (quando leu, resultado)
        self._formato: tuple[float, dict | None] = (0.0, None)  # (quando leu, formato da webcam)
        self.create_subscription(Detection2DArray, self.get_parameter("detections_topic").value, self._on_detections, 1)
        self.create_subscription(String, "/reaction/rotina_status", self._on_status, 20)
        self._corpo = "livre"  # /reaction/corpo: livre | rotina | mantendo:<postura>
        self._voz: dict = {}  # último /voz/estado
        self.create_subscription(String, "/reaction/corpo", self._on_corpo, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(String, "/voz/estado", self._on_voz, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self._get = self.create_client(GetParameters, "/reaction_node/get_parameters")
        self._set = self.create_client(SetParameters, "/reaction_node/set_parameters")
        self._set_corpo = self.create_client(SetParameters, "/body_node/set_parameters")
        self._get_corpo = self.create_client(GetParameters, "/body_node/get_parameters")
        self._get_rec = self.create_client(GetParameters, "/face_recognition_node/get_parameters")
        self._cadastrar = self.create_client(Cadastrar, "/face_recognition_node/cadastrar")

    def _on_detections(self, msg: Detection2DArray) -> None:
        caixas = [{"nome": d.results[0].id, "nota": round(d.results[0].score, 2), "caixa_px": round(d.bbox.size_y), "x": round(d.bbox.center.x)}
                  for d in msg.detections if d.results]
        agora = time.monotonic()
        with self._lock:
            self._deteccoes, self._deteccao_em = caixas, agora
            self._quadros.append(agora)

    def _on_corpo(self, msg: String) -> None:
        with self._lock:
            self._corpo = msg.data

    def _on_voz(self, msg: String) -> None:
        try:
            dados = json.loads(msg.data)
        except ValueError:
            return
        if isinstance(dados, dict):
            with self._lock:
                self._voz = dados

    def _on_status(self, msg: String) -> None:
        with self._lock:
            registrar_status(self._status, msg.data, time.time())
            if msg.data.startswith(("inicializando", "pronto: em equilíbrio")):
                self._armado = True
            elif msg.data.startswith("desarmado"):
                self._armado = False

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
        return valor_param(resposta.values[0])

    def _param_fixo(self, no: str, cliente: object, nome: str, nos: set) -> object | None:
        """Parâmetro que não muda enquanto o nó vive: pergunta uma vez, sem pesar a cada 1 s do painel."""
        chave = (no, nome)
        if no not in nos:
            self._params.pop(chave, None)
            return None
        valor, perguntou_em = self._params.get(chave, (None, float("-inf")))
        if valor is None and time.monotonic() - perguntou_em >= PARAM_RETRY_S:
            resposta = self._chamar(cliente, GetParameters.Request(names=[nome]), 1.0)
            valor = valor_param(resposta.values[0]) if resposta is not None and resposta.values else None
            self._params[chave] = (valor, time.monotonic())
        return valor

    def armado(self, nos: set) -> bool | None:
        """O robô está armado? None = não deu para saber (a tela trata como "pode estar").

        Vale o que o body_node anunciou por último. Olhar se a linha "pronto" ainda está no histórico
        dizia "desarmado" com o robô andando (a linha saía) e "armado" numa subida desarmada (a antiga
        ficava). Se o painel subiu depois do anúncio, pergunta ao nó: `armed` não muda enquanto ele vive.
        """
        if "body_node" not in nos:
            with self._lock:
                self._armado = None
            return False
        with self._lock:
            anunciado = self._armado
        if anunciado is not None:
            return anunciado
        valor = self._param_fixo("body_node", self._get_corpo, "armed", nos)
        return None if valor is None else str(valor).lower() == "true"

    def set_reacao(self, nome: str, valor: object) -> str:
        return self._set_param(self._set, "reaction_node", nome, valor)

    def _set_param(self, cliente: object, no: str, nome: str, valor: object) -> str:
        if isinstance(valor, bool):
            pv = ParameterValue(type=ParameterType.PARAMETER_BOOL, bool_value=valor)
        else:
            pv = ParameterValue(type=ParameterType.PARAMETER_STRING, string_value=str(valor))
        resposta = self._chamar(cliente, SetParameters.Request(parameters=[ParameterMsg(name=nome, value=pv)]), 3.0)
        if resposta is None:
            return f"{no} não respondeu (a rotina está de pé?)"
        r = resposta.results[0]
        return "ok" if r.successful else r.reason

    def cadastrar(self, nome: str, fotos_b64: list[str], adicionar: bool = False) -> dict:
        if len(fotos_b64) > FOTOS_MAX:
            return {"ok": False, "mensagem": f"{len(fotos_b64)} fotos: o máximo é {FOTOS_MAX} por envio. Nada foi alterado."}
        fotos = [CompressedImage(format="jpeg", data=array.array("B", base64.b64decode(f.split(",", 1)[-1]))) for f in fotos_b64]
        resposta = self._chamar(self._cadastrar, Cadastrar.Request(nome=nome, fotos=fotos, adicionar=adicionar), 90.0)
        if resposta is None:
            return {"ok": False, "mensagem": "face_recognition_node não respondeu (a rotina está de pé?)"}
        return {"ok": resposta.ok, "mensagem": resposta.mensagem, "tem_rotina": nome in self.pessoas_com_rotina()}

    # ---- estado e operação ------------------------------------------------------------------
    def formato_webcam(self) -> dict | None:
        """Só leitura (não disputa a câmera com o nó). None sem webcam ou sem o v4l2-ctl: a tela só não mostra."""
        lido_em, resultado = self._formato
        if time.monotonic() - lido_em > FORMATO_CACHE_S:
            caminho = next((c for c in sorted(glob.glob(WEBCAM_GLOB)) if "RealSense" not in c), None)
            resultado = None if caminho is None else ler_formato_webcam(
                _comando("v4l2-ctl", "-d", caminho, "--get-fmt-video", timeout=2.0),
                _comando("v4l2-ctl", "-d", caminho, "--get-parm", timeout=2.0))
            self._formato = (time.monotonic(), resultado)
        return resultado

    def webcam(self, rotina_desde: float | None) -> dict:
        """Webcam USB conectada? Desde quando, quantas quedas, e se a rotina precisa subir de novo.

        Uma reconexão troca o /dev/videoN: o v4l2_camera_node fica preso no antigo e para de mandar
        imagem até a rotina subir de novo.
        """
        desde = webcam_usb()
        with self._lock:
            if desde != self._webcam_vista:
                if self._webcam_vista is not None:  # estava conectada: caiu (e talvez já voltou)
                    self._webcam_quedas += 1
                self._webcam_vista = desde
            quedas = self._webcam_quedas
        return {
            "nome": webcam_nome(),
            "formato": self.formato_webcam(),
            "conectada": desde is not None,
            "desde": time.strftime("%H:%M:%S", time.localtime(desde)) if desde else None,
            "quedas": quedas,
            "reiniciar": desde is not None and rotina_desde is not None and desde > rotina_desde,
        }

    def caixa(self) -> dict:
        lido_em, resultado = self._caixa
        if time.monotonic() - lido_em > CAIXA_CACHE_S:
            resultado = caixa_de_som(caixa_atual(ARQ_CAIXA))
            self._caixa = (time.monotonic(), resultado)
        return resultado

    def caixas(self, procurar: bool = False) -> list[dict]:
        """As caixas que o robô conhece; `procurar` faz antes uma busca curta, só quando pedida."""
        if procurar:
            _comando("bluetoothctl", "--timeout", "8", "scan", "on", timeout=12.0)
        atual = caixa_atual(ARQ_CAIXA)
        return [{**d, "atual": d["mac"] == atual, "padrao": d["mac"] == CAIXA_PADRAO}
                for d in ler_dispositivos(_comando("bluetoothctl", "devices", timeout=5.0))]

    def usar_caixa(self, mac: str) -> dict:
        """Pareia, conecta e passa a usar a caixa. Só salva se conectou; a anterior vale até lá."""
        if not mac_valido(mac):
            return {"ok": False, "mensagem": f"endereço inválido: {mac!r}"}
        for acao in ("pair", "trust", "connect"):
            _comando("bluetoothctl", acao, mac)
        if "Connected: yes" not in _comando("bluetoothctl", "info", mac, timeout=5.0):
            return {"ok": False, "mensagem": "não conectou: ligue a caixa em modo de pareamento e tente de novo. "
                                             "A caixa anterior continua valendo."}
        sink = None
        for _ in range(10):
            linhas = _comando("pactl", "list", "short", "sinks", timeout=3.0).splitlines()
            sink = next((l.split()[1] for l in linhas if nome_do_sink(mac) in l and len(l.split()) > 1), None)
            if sink:
                break
            time.sleep(1.0)
        if sink is None:
            return {"ok": False, "mensagem": "conectou, mas não apareceu como saída de som. A caixa anterior continua valendo."}
        _comando("pactl", "set-default-sink", sink, timeout=3.0)
        if mac == CAIXA_PADRAO:
            if os.path.exists(ARQ_CAIXA):
                os.remove(ARQ_CAIXA)
        else:
            os.makedirs(os.path.dirname(ARQ_CAIXA), exist_ok=True)
            with open(ARQ_CAIXA, "w") as f:
                f.write(mac + "\n")
        self._caixa = (0.0, {})
        tocar("agora")
        return {"ok": True, "mensagem": "caixa em uso; ouviu o bipe?"}

    # ---- pessoas ----------------------------------------------------------------------------
    def _mapa_pacote(self) -> dict:
        with open(os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "reactions.yaml")) as f:
            return load_reactions(yaml.safe_load(f))

    def _fotos(self) -> dict:
        try:
            with open(f"{DB_BASE}_{MODEL_NAME}.json") as f:
                return json.load(f).get("counts", {})
        except (OSError, ValueError):
            return {}

    def pessoas(self) -> list[dict]:
        """Todo mundo com foto ou rotina: sem foto não é reconhecido; sem rotina não é cumprimentado."""
        try:
            pacote = self._mapa_pacote()
        except Exception:
            pacote = {}
        com_rotina = set(self.pessoas_com_rotina())
        fotos = self._fotos()
        return [{"nome": n, "fotos": fotos.get(n, 0), "rotina": n in com_rotina, "padrao": n in pacote}
                for n in sorted(com_rotina | set(fotos))]

    def _ler_extras(self) -> dict:
        try:
            with open(ARQ_REACOES) as f:
                return yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            return {}

    def _gravar_extras(self, extras: dict) -> None:
        os.makedirs(os.path.dirname(ARQ_REACOES), exist_ok=True)
        with open(ARQ_REACOES, "w") as f:
            yaml.safe_dump(extras, f, allow_unicode=True, sort_keys=False)

    def salvar_pessoa(self, nome: str, tratamento: str, falado: str) -> dict:
        """Rotina padrão para uma pessoa nova. Quem está no reactions.yaml do pacote não muda por aqui."""
        nome = nome.strip()
        if not NOME_VALIDO.match(nome) or nome == "desconhecido":
            return {"ok": False, "mensagem": f"nome inválido {nome!r}: use minúsculas, números e _"}
        if nome in self._mapa_pacote():
            return {"ok": False, "mensagem": f"{nome} já tem a rotina padrão do projeto"}
        try:
            rotina = rotina_padrao(tratamento, falado.strip() or nome_falado(nome))
        except ValueError as exc:
            return {"ok": False, "mensagem": str(exc)}
        extras = self._ler_extras()
        extras[nome] = rotina
        self._gravar_extras(extras)
        return {"ok": True, "mensagem": f"rotina de {nome} salva; vale na próxima subida"}

    def remover_pessoa(self, nome: str) -> dict:
        """Apaga as fotos (e a rotina acrescentada pelo painel). Com a rotina de pé, o reconhecimento
        tem o banco na memória e o regravaria: só com ela parada."""
        if not NOME_VALIDO.match(nome):
            return {"ok": False, "mensagem": f"nome inválido {nome!r}"}
        if "face_recognition_node" in self.get_node_names():
            return {"ok": False, "mensagem": "pare a rotina antes de remover (para trocar a foto, basta cadastrar de novo)"}
        banco = IdentityStore(DB_BASE, model_name=MODEL_NAME)
        banco.load()
        if banco.embeddings.pop(nome, None) is not None:
            banco.save()
        extras = self._ler_extras()
        if extras.pop(nome, None) is not None:
            self._gravar_extras(extras)
        return {"ok": True, "mensagem": f"{nome} removido"}

    def pessoas_com_rotina(self) -> list[str]:
        try:
            base = os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "reactions.yaml")
            return sorted(carregar_reacoes(base, ARQ_REACOES)[0])
        except Exception:
            return []

    def estado(self) -> dict:
        agora = time.monotonic()
        with self._lock:
            quadros = [t for t in self._quadros if agora - t <= RECENTE_S]
            deteccoes = self._deteccoes if agora - self._deteccao_em <= RECENTE_S else []
            deteccao_viva = agora - self._deteccao_em <= RECENTE_S
            status = list(self._status)
            corpo, voz = self._corpo, dict(self._voz)
        nos = set(self.get_node_names())
        desde = sessao_criada()
        # Status de uma subida anterior não diz nada sobre esta.
        ultimo = status[-1][1] if status and (desde is None or status[-1][0] >= desde) else ""
        rotina = sessao_de_pe() or "body_node" in nos  # também quando o launch subiu à mão
        fase = "parando" if self._parando.is_set() else estagio(ultimo) if rotina and ultimo else "subindo" if rotina or self._subindo.is_set() else "rotina parada"
        return {
            "rotina_de_pe": rotina,
            "camera": {"ok": self.count_publishers(self._image_topic) > 0},
            # O aviso só vale se a imagem não voltou (com vigia_camera:=true, ela volta sozinha).
            "rotina_ha_s": round(time.time() - desde) if desde else None,
            "subindo": self._subindo.is_set(),
            "parando": self._parando.is_set(),
            "subida_erro": self._subida_erro,
            "operacao_pendente": bool(rotina and desde and self._operacao_alterada_em > desde),
            "webcam": {**(w := self.webcam(desde)), "reiniciar": w["reiniciar"] and not deteccao_viva},
            "caixa": self.caixa(),
            "reconhecimento": {"ok": deteccao_viva, "no": "face_recognition_node" in nos,
                               "fps": round(len(quadros) / RECENTE_S, 1),
                               "limiar": self._param_fixo("face_recognition_node", self._get_rec, "similarity_threshold", nos)},
            "vistos": deteccoes,
            "estagio": fase,
            "body_node": "body_node" in nos,
            "automatico": self.param_reacao("automatico") if "reaction_node" in nos else None,
            "reaction_node": "reaction_node" in nos,
            "voz_node": "voz_node" in nos,
            # ponytail: guardado enquanto o nó vive; um `ros2 param set` à mão não aparece aqui.
            "estagios": self._param_fixo("body_node", self._get_corpo, "estagios", nos),
            "armado": self.armado(nos),
            "status": _linhas_status(status[-EVENTOS_NA_TELA:]),
            "pessoas": self.pessoas(),
            # Sem o nó, o último valor guardado é velho: não mostra posição nem microfone.
            "corpo": corpo if "body_node" in nos else "livre",
            "voz": voz if "voz_node" in nos else {},
        }

    def _subir(self, args: list[str]) -> None:
        """Roda o script de subida e guarda o motivo se ele parar: sem isto a tela ficava em "subindo…".

        Saída em arquivo, não em pipe: o servidor de voz e o tmux que o script deixa de pé herdariam o
        pipe, e esperar por ele nunca terminaria.
        """
        try:
            with tempfile.TemporaryFile("w+") as saida:
                codigo = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=saida, stderr=subprocess.STDOUT).wait()
                saida.seek(0)
                linhas = saida.read().strip().splitlines()
            if linhas:
                self.get_logger().info("subida:\n" + "\n".join(linhas))
            if codigo != 0:
                self._falha_subida(linhas[-1] if linhas else f"o script terminou com erro {codigo}")
        except Exception as exc:
            self._falha_subida(repr(exc))
        finally:
            self._subindo.clear()

    def _falha_subida(self, motivo: str) -> None:
        self._subida_erro = motivo
        with self._lock:
            registrar_status(self._status, f"falha ao subir: {motivo}", time.time())

    def _encerrar_sessao(self) -> None:
        try:
            fechar_sessao_quando_terminar()
        finally:
            self._parando.clear()

    def acao(self, nome: str) -> str:
        script = os.path.join(REPO, "scripts", "robo_rotina_cumprimento.sh")
        if nome in ("subir_desarmado", "subir_armado"):
            if sessao_de_pe() or "body_node" in self.get_node_names():
                return "a rotina já está de pé"
            if self._subindo.is_set():
                return "já está subindo: aguarde"
            self._subindo.set()
            self._subida_erro = None
            args = [script] + (["--controle"] if nome == "subir_armado" else [])
            threading.Thread(target=self._subir, args=(args,), daemon=True).start()
            return "subindo… (acompanhe o estágio)"
        if nome == "parar":
            if not sessao_de_pe():
                if _comando("pgrep", "-f", "robo_levantar.py", timeout=3.0).strip():
                    return "o robô está levantando: para abortar, use o combo de parar do controle"
                if "body_node" in self.get_node_names():
                    return "a rotina foi iniciada à mão: pare com Ctrl+C no terminal dela"
                return "nenhuma rotina de pé"
            if self._parando.is_set():
                return "já está parando: aguarde os braços voltarem"
            self._parando.set()
            subprocess.run(["tmux", "send-keys", "-t", f"{SESSAO}:rotina", "C-c"])
            # Como o F2+DOWN: fecha a sessão só depois que o launch saiu (braços devolvidos); sem
            # isso o próximo "Subir" (ou F2+UP) dizia "a rotina já está de pé".
            threading.Thread(target=self._encerrar_sessao, daemon=True).start()
            return "parando (a sessão fecha quando os braços voltarem)"
        if nome == "agora":
            return self.set_reacao("cumprimentar_agora", "agora")
        if nome == "liberar":  # todos podem ser cumprimentados de novo já (sem os 5 min)
            return self.set_reacao("liberar", "todos")
        if nome in ORDENS:  # o mesmo comando da voz e do F3+X: o nó de voz decide se pode
            if "voz_node" not in self.get_node_names():
                return "nó de voz fora do ar: não enviei"
            enviar_voz(f"comando:{nome}")
            return f"{ORDENS[nome]} enviado"
        if nome == "automatico":
            atual = self.param_reacao("automatico")
            return "reaction_node não respondeu" if atual is None else self.set_reacao("automatico", not atual)
        return f"ação desconhecida {nome!r}"

    def _operacao_padrao(self) -> dict:
        with open(os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "operacao.yaml")) as f:
            return yaml.safe_load(f)["/**"]["ros__parameters"]

    def operacao_info(self) -> dict:
        """Para a tela mostrar o padrão e a faixa de cada campo; quem decide é o salvar_operacao."""
        return {"padrao": self._operacao_padrao(), "limites": LIMITES_OPERACAO}

    def operacao(self) -> dict:
        # O arquivo salvo por cima dos padrões do pacote: um salvo antes de um campo novo existir
        # ainda mostra e salva esse campo.
        valores = self._operacao_padrao()
        if os.path.exists(self._operacao_file):
            with open(self._operacao_file) as f:
                valores.update(migrar_estagios(yaml.safe_load(f)["/**"]["ros__parameters"]))
        return valores

    def restaurar_operacao(self) -> str:
        if os.path.exists(self._operacao_file):
            os.remove(self._operacao_file)
        self._operacao_alterada_em = time.time()
        return "padrões restaurados; valem na próxima subida"

    def salvar_operacao(self, novos: dict) -> str:
        atual = self.operacao()
        for campo in CAMPOS_OPERACAO:
            if campo in novos:
                tipo = type(atual[campo])
                valor = novos[campo]
                try:
                    atual[campo] = (valor in (True, "true", "on", "1")) if tipo is bool else tipo(valor)
                except ValueError:
                    raise ValueError(f"{campo}: {valor!r} não é um valor válido") from None
                if campo == "estagios":
                    # Um nome errado derrubaria o body_node na próxima subida: recusa já ao salvar.
                    parse_stages(atual[campo])
        validar_operacao(atual)
        os.makedirs(os.path.dirname(self._operacao_file), exist_ok=True)
        with open(self._operacao_file, "w") as f:
            yaml.safe_dump({"/**": {"ros__parameters": atual}}, f, allow_unicode=True, sort_keys=False)
        self._operacao_alterada_em = time.time()
        return f"salvo em {self._operacao_file}; vale na próxima subida da rotina"

    def aplicar_estagios(self, lista: str) -> dict:
        """Grava os estágios e, com o body_node de pé, já valem no próximo cumprimento."""
        try:
            parse_stages(lista)
        except ValueError as exc:
            return {"ok": False, "mensagem": str(exc)}
        vivo = "body_node" in self.get_node_names()
        if vivo:
            resultado = self._set_param(self._set_corpo, "body_node", "estagios", lista)
            if resultado != "ok":  # não grava o que o robô recusou: tela e robô ficam iguais
                return {"ok": False, "mensagem": resultado}
            self._params[("body_node", "estagios")] = (lista, time.monotonic())
        pendente_desde = self._operacao_alterada_em
        self.salvar_operacao({"estagios": lista})
        if vivo:  # já valeu: não é ajuste pendente para a próxima subida
            self._operacao_alterada_em = pendente_desde
        return {"ok": True, "mensagem": "valendo já" if vivo else "vale na próxima subida"}

    def diagnostico(self) -> str:
        """Tudo de uma vez, em texto, para olhar ou mandar para alguém quando não há cabo."""
        with self._lock:
            status = list(self._status)
        eventos = "\n".join(f"{s['hora']}  {s['texto']}" + (f"  (x{s['repeticoes']})" if s["repeticoes"] > 1 else "")
                            for s in _linhas_status(status))
        tela = _comando("tmux", "capture-pane", "-p", "-t", f"{SESSAO}:rotina", "-S", "-200", timeout=3.0)
        return (f"Diagnóstico do G1, {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"== Estado ==\n{json.dumps(self.estado(), ensure_ascii=False, indent=2)}\n\n"
                f"== Operação salva ==\n{json.dumps(self.operacao(), ensure_ascii=False, indent=2)}\n\n"
                f"== Eventos ==\n{eventos or '(nenhum)'}\n\n"
                f"== Janela rotina (tmux) ==\n{tela.strip() or '(sem sessão)'}\n")


def _linhas_status(status: list) -> list[dict]:
    """Do mais novo para o mais velho, como a tela mostra."""
    return [{"hora": time.strftime("%H:%M:%S", time.localtime(t)), "texto": s, "repeticoes": n} for t, s, n in status][::-1]


def mesma_origem(origem: str | None, host: str | None) -> bool:
    """Um POST de outro site (a página aberta no celular conectado ao robô) traz o Origin dele."""
    return origem is None or urlsplit(origem).netloc == host


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
            tamanho = int(self.headers.get("Content-Length", 0))
            if tamanho > CORPO_MAX:
                raise ValueError("pedido grande demais")
            return json.loads(self.rfile.read(tamanho) or b"{}")

        def do_GET(self) -> None:
            try:
                self._get()
            except Exception as exc:  # um pedido ruim não derruba o painel
                self._json({"mensagem": f"erro: {exc!r}"}, 500)

        def _get(self) -> None:
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")  # o celular não fica com a página antiga
                self.end_headers()
                self.wfile.write(pagina)
            elif self.path == "/estado":
                self._json(painel.estado())
            elif self.path == "/operacao":
                self._json(painel.operacao())
            elif self.path == "/operacao/info":
                self._json(painel.operacao_info())
            elif self.path == "/diagnostico":
                corpo = painel.diagnostico().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif self.path == "/caixas":
                self._json(painel.caixas())
            else:
                self._json({"erro": "não existe"}, 404)

        def do_POST(self) -> None:
            if not mesma_origem(self.headers.get("Origin"), self.headers.get("Host")):
                self._json({"mensagem": "pedido de outra origem recusado"}, 403)
                return
            try:
                if self.path.startswith("/acao/"):
                    self._json({"mensagem": painel.acao(self.path[len("/acao/"):])})
                elif self.path == "/operacao":
                    try:
                        self._json({"ok": True, "mensagem": painel.salvar_operacao(self._corpo())})
                    except ValueError as exc:
                        self._json({"ok": False, "mensagem": str(exc)})
                elif self.path == "/estagios":
                    self._json(painel.aplicar_estagios(str(self._corpo().get("estagios", ""))))
                elif self.path == "/operacao/restaurar":
                    self._json({"mensagem": painel.restaurar_operacao()})
                elif self.path == "/pessoa":
                    d = self._corpo()
                    self._json(painel.salvar_pessoa(str(d.get("nome", "")), str(d.get("tratamento", "")), str(d.get("falado", ""))))
                elif self.path == "/pessoa/remover":
                    self._json(painel.remover_pessoa(str(self._corpo().get("nome", ""))))
                elif self.path == "/caixa/procurar":
                    self._json(painel.caixas(procurar=True))
                elif self.path == "/caixa/usar":
                    self._json(painel.usar_caixa(str(self._corpo().get("mac", ""))))
                elif self.path == "/caixa/testar":
                    tocar("agora")
                    self._json({"mensagem": "bipe enviado; ouviu?"})
                elif self.path == "/cadastrar":
                    dados = self._corpo()
                    self._json(painel.cadastrar(str(dados.get("nome", "")), list(dados.get("fotos", [])), dados.get("adicionar") is True))
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
