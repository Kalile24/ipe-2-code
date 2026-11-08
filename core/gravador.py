"""Gravação do microfone via arecord, só em memória (o áudio nunca vai para o disco)."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time


class Gravador:
    def __init__(self, dispositivo: str, comando: list[str] | None = None) -> None:
        self._comando = comando or [
            "arecord", "-q", "-D", dispositivo, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw",
        ]
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._pcm = bytearray()

    def presente(self) -> bool:
        """Há alguma placa de captura? Nunca levanta."""
        try:
            saida = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=3).stdout
            return "card" in saida
        except Exception:
            return False

    def iniciar(self) -> None:
        self._pcm = bytearray()
        # sessão própria: parar() mata o grupo, senão um filho segura o pipe aberto
        self._proc = subprocess.Popen(
            self._comando, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0, start_new_session=True
        )
        self._thread = threading.Thread(target=self._ler, args=(self._proc, self._pcm), daemon=True)
        self._thread.start()
        # arecord com dispositivo errado sai na hora: sem isto o aperto gravaria silêncio
        fim = time.monotonic() + 0.2
        while time.monotonic() < fim:
            if self._proc.poll() is not None:
                codigo = self._proc.returncode
                self.parar()
                raise OSError(f"{self._comando[0]} saiu na partida (código {codigo})")
            time.sleep(0.02)

    @staticmethod
    def _ler(proc: subprocess.Popen, pcm: bytearray) -> None:  # o pipe enche em ~2 s se ninguém ler
        while True:
            pedaco = proc.stdout.read(4096)
            if not pedaco:
                return
            pcm.extend(pedaco)

    def parar(self) -> bytes:
        proc, thread = self._proc, self._thread
        if proc is None:
            return bytes(self._pcm)
        self._proc = None
        for sinal, espera in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(proc.pid, sinal)
            except ProcessLookupError:
                pass
            try:
                proc.wait(espera)
                break
            except subprocess.TimeoutExpired:
                pass
        thread.join(2.0)
        proc.stdout.close()
        return bytes(self._pcm)
