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
import glob
import json
import os
import re
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

from core.bipes import tocar
from core.caixa import CAIXA_PADRAO, caixa_atual, ler_dispositivos, mac_valido, nome_do_sink
from core.config import DB_PATH, MODEL_NAME
from core.identity_store import IdentityStore
from core.pessoas import carregar_reacoes, nome_falado, rotina_padrao
from core.reaction_policy import load_reactions
from core.stages import parse_stages
from robot_reaction_interfaces.srv import Cadastrar

REPO = os.path.expanduser(os.environ.get("IPE_REPO", "~/ipe-2-code"))
SESSAO = "rotina"
RECENTE_S = 2.0  # câmera/detecção mais velha que isso conta como parada
CAMPOS_OPERACAO = (  # o que o formulário pode mudar no operacao.yaml (o resto fica como está)
    "estagios", "altura_caixa_alvo_px", "vx", "vyaw_max", "vyaw_min", "kp_giro", "inverter_giro", "centro_ok",
    "centro_para_andar", "centro_chegada", "perda_rosto_s", "desistir_s", "tempo_max_s", "avisos_voz",
)
FIM = ("fim", "falhou", "interrompida", "desistiu", "rejeitada")
WEBCAM_GLOB = "/dev/v4l/by-id/*-video-index0"  # o mesmo que o robo_rotina_cumprimento.sh usa
ARQ_CAIXA = os.path.join(REPO, "data", "caixa.txt")
ARQ_REACOES = os.path.join(REPO, "data", "reactions.yaml")
DB_BASE = DB_PATH
NOME_VALIDO = re.compile(r"^[a-z0-9_]+$")
CAIXA_CACHE_S = 3.0  # bluetoothctl/pactl a cada pedido pesariam no painel


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
        self._webcam_vista: float | None = webcam_usb()  # última hora de conexão observada
        self._webcam_quedas = 0  # desconexões/reconexões vistas desde que o painel subiu
        self._caixa: tuple[float, dict] = (0.0, {})  # (quando leu, resultado)
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
        nos = set(self.get_node_names())
        ultimo = status[-1][1] if status else ""
        rotina = sessao_de_pe() or "body_node" in nos  # também quando o launch subiu à mão
        return {
            "rotina_de_pe": rotina,
            "camera": {"ok": self.count_publishers(self._image_topic) > 0},
            # O camera_vigia reinicia a câmera sozinho: o aviso só vale se a imagem não voltou.
            "webcam": {**(w := self.webcam(sessao_criada())), "reiniciar": w["reiniciar"] and not deteccao_viva},
            "caixa": self.caixa(),
            "reconhecimento": {"ok": deteccao_viva, "no": "face_recognition_node" in nos,
                               "fps": round(len(quadros) / RECENTE_S, 1)},
            "vistos": deteccoes,
            "estagio": estagio(ultimo) if rotina else "rotina parada",
            "body_node": "body_node" in nos,
            "automatico": self.param_reacao("automatico") if "reaction_node" in nos else None,
            "armado": any("pronto: em equilíbrio" in s or "inicializando" in s for _, s in status),
            "status": [{"hora": time.strftime("%H:%M:%S", time.localtime(t)), "texto": s} for t, s in status[-15:]][::-1],
            "pessoas": self.pessoas(),
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
            # Como o F2+DOWN: fecha a sessão só depois que o launch saiu (braços devolvidos); sem
            # isso o próximo "Subir" (ou F2+UP) dizia "a rotina já está de pé".
            threading.Thread(target=fechar_sessao_quando_terminar, daemon=True).start()
            return "parando (a sessão fecha quando os braços voltarem)"
        if nome == "agora":
            return self.set_reacao("cumprimentar_agora", "agora")
        if nome == "liberar":  # todos podem ser cumprimentados de novo já (sem os 5 min)
            return self.set_reacao("liberar", "todos")
        if nome == "automatico":
            atual = self.param_reacao("automatico")
            return "reaction_node não respondeu" if atual is None else self.set_reacao("automatico", not atual)
        return f"ação desconhecida {nome!r}"

    def operacao(self) -> dict:
        # O arquivo salvo por cima dos padrões do pacote: um salvo antes de um campo novo existir
        # ainda mostra e salva esse campo.
        padrao = os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "operacao.yaml")
        with open(padrao) as f:
            valores = yaml.safe_load(f)["/**"]["ros__parameters"]
        if os.path.exists(self._operacao_file):
            with open(self._operacao_file) as f:
                valores.update(yaml.safe_load(f)["/**"]["ros__parameters"])
        return valores

    def restaurar_operacao(self) -> str:
        if os.path.exists(self._operacao_file):
            os.remove(self._operacao_file)
        return "padrões restaurados; valem na próxima subida"

    def salvar_operacao(self, novos: dict) -> str:
        atual = self.operacao()
        for campo in CAMPOS_OPERACAO:
            if campo in novos:
                tipo = type(atual[campo])
                valor = novos[campo]
                atual[campo] = (valor in (True, "true", "on", "1")) if tipo is bool else tipo(valor)
                if campo == "estagios":
                    # Um nome errado derrubaria o body_node na próxima subida: recusa já ao salvar.
                    parse_stages(atual[campo])
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
            elif self.path == "/caixas":
                self._json(painel.caixas())
            else:
                self._json({"erro": "não existe"}, 404)

        def do_POST(self) -> None:
            try:
                if self.path.startswith("/acao/"):
                    self._json({"mensagem": painel.acao(self.path[len("/acao/"):])})
                elif self.path == "/operacao":
                    self._json({"mensagem": painel.salvar_operacao(self._corpo())})
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
