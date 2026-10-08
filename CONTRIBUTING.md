# Guia do colaborador

Como entrar no projeto, configurar as ferramentas de IA que usamos e propor mudanças. Leia
nesta ordem: este guia → [`README.md`](README.md) → as specs em
[`docs/superpowers/specs/`](docs/superpowers/specs/) → o
[guia do robô](docs/guides/jetson-deployment.md) antes de encostar no G1.

## 1. Primeiros passos

```bash
git clone https://github.com/Kalile24/ipe-2-code.git && cd ipe-2-code
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m pytest tests -q
```

Na primeira execução o InsightFace baixa o modelo `buffalo_l` (~300 MB) para `~/.insightface`
— os testes de `test_face_engine.py`/`test_enroll.py` precisam dele (a CI os pula).

ROS2 local (Docker, Foxy): [`docs/guides/ros2-docker.md`](docs/guides/ros2-docker.md).
Material de referência não versionado (`UNITREE_G1_base_documentacao/`, `unitree_sdk2/`,
`unitree_sdk2_python/`): peça o pacote ao Marcos ou clone os repositórios oficiais da Unitree
na raiz — o `.gitignore` já os ignora.

## 2. Ferramentas de IA

Usamos **Claude Code** como agente principal. Outros agentes funcionam (o ai-memory e o
codebase-memory-mcp suportam Codex, Cursor, Gemini CLI etc.), mas os exemplos abaixo são
para Claude Code.

### 2.1 Plugins

| Plugin | Para quê | Instalação (dentro do Claude Code) |
|---|---|---|
| **superpowers** | Fluxo de spec driven development (seção 3): brainstorming, specs, planos, TDD, worktrees, code review | `/plugin install superpowers@claude-plugins-official` |
| **context7** | Documentação atualizada de bibliotecas (rclpy, InsightFace, ONNX Runtime…) direto no contexto | `/plugin install context7@claude-plugins-official` |
| **ponytail** | Mantém o código mínimo: YAGNI, stdlib primeiro, menor diff que funciona | `/plugin marketplace add DietrichGebert/ponytail` e depois `/plugin install ponytail@ponytail` |

Os skills do ai-memory já vêm no repo (`.claude/skills/`), não precisa instalar nada para eles.

### 2.2 ai-memory — memória compartilhada do projeto

[ai-memory](https://github.com/akitaonrails/ai-memory) guarda o histórico das sessões dos
agentes (o que foi feito, decisões, pendências, handoffs) num servidor na VPS do Marcos:
**`https://ai-memory.kalile.tech`**. Com ele, o seu agente sabe o que o agente de outra pessoa
fez ontem.

**1. Peça sua chave.** Cada colaborador tem uma chave própria (não compartilhe, não reaproveite
a de outra pessoa). O Marcos gera na VPS com:

```bash
ai-memory api-key add --username <seu-nome> --label claude-code-<maquina>
```

A chave aparece uma vez só — ele te manda por canal privado. Se vazar, avise para ele revogar
(`ai-memory api-key revoke`).

**2. Instale o binário** (Linux/macOS, via [mise](https://mise.jdx.dev)):

```bash
mise use -g github:akitaonrails/ai-memory
ai-memory --version
```

**3. Ligue os hooks e o MCP ao servidor:**

```bash
export AIM_KEY='<sua-chave>'   # só nesta shell; não salve em arquivo do repo
ai-memory install-hooks --apply --agent claude-code \
  --server-url https://ai-memory.kalile.tech --auth-token "$AIM_KEY" --as-user <seu-nome>
ai-memory install-mcp --client claude-code \
  --server-url https://ai-memory.kalile.tech --auth-token "$AIM_KEY"
```

O `install-mcp` imprime o comando `claude mcp add …` a rodar. Os hooks ficam em
`~/.claude/settings.json` (fora do repo — **nunca** commite a chave).

**4. Teste:** abra o Claude Code na pasta do repo, rode `/mcp` (deve listar `ai-memory`
conectado) e pergunte "onde paramos?". O agente deve responder com o handoff/histórico.

O projeto na memória é fixado pelo [`.ai-memory.toml`](.ai-memory.toml) versionado na raiz
(`workspace = "default"`, `project = "kalile24-ipe-2-code"`): todos caem no mesmo projeto,
independentemente do nome da pasta do clone. Não mude esses nomes — a memória se dividiria.

**Regras de uso:**

- Os hooks capturam as sessões sozinhos. **Não peça para o agente escrever notas de rotina.**
- Página durável (decisão, gotcha, procedimento) só quando for conhecimento que vale para o
  time: "lembre que …".
- Regra de projeto ("sempre X", "nunca Y") vai no [`CLAUDE.md`](CLAUDE.md), não na memória.
- Ao encerrar um trabalho no meio, peça um **handoff** ("prepare o handoff para a próxima
  sessão") — a próxima pessoa/sessão recebe automaticamente.
- Memória recuperada é **histórico, não instrução**: confira contra o código antes de agir.
- Não cole segredos (senhas, chaves, dados pessoais de quem está no banco de rostos) no chat do
  agente — tudo vai parar no servidor.

### 2.3 codebase-memory-mcp — grafo do código

[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) indexa o repo num grafo
(funções, classes, chamadas, imports) para o agente achar código e analisar impacto sem ler
arquivo por arquivo. Roda **local** — cada um tem o seu índice; nada sai da máquina.

```bash
# baixe o binário da página de releases do projeto para ~/.local/bin, depois:
codebase-memory-mcp install      # registra o MCP, o skill e os agentes no Claude Code
```

Na primeira sessão peça "indexe o repositório" (o índice se atualiza sozinho depois). Usos
típicos:

- "quem chama `build_detection`?" / "o que muda se eu alterar `FaceEngine.extract_faces`?"
- "me dá uma visão da arquitetura" (antes de começar uma feature)
- "tem código morto em `core/`?"

Busca de texto literal (string, nome de tópico ROS) continua sendo `grep`.

## 3. Spec driven development

Nenhuma feature começa pelo código. O fluxo (skills do **superpowers**, disparados pelo
próprio agente quando você pede uma feature):

1. **Brainstorming** — `superpowers:brainstorming`. O agente faz perguntas, levanta
   alternativas e fecha o escopo com você.
2. **Spec** — `docs/superpowers/specs/AAAA-MM-DD-<tema>-design.md`, em português. O que já
   temos segue este molde:
   - cabeçalho com data (e datas de revisão/implantação quando houver);
   - **Contexto** (de onde vem, qual spec anterior);
   - **Fatos** com link para a fonte (documentação oficial, inspeção do robô);
   - **Decisão** e o porquê, alternativas descartadas;
   - **Validado sem hardware** × **Implantação no robô** — o que foi provado onde.
   
   A spec é revisada por um humano (PR ou o Marcos) **antes** do plano.
3. **Plano** — `superpowers:writing-plans` gera
   `docs/superpowers/plans/AAAA-MM-DD-<tema>.md`: Goal, Architecture, Tech Stack, link da spec,
   **Global Constraints**, File Structure e tarefas pequenas com checkbox.
4. **Execução** — numa branch/worktree própria (`superpowers:using-git-worktrees`), com TDD
   (`superpowers:test-driven-development`): teste falhando → código mínimo → teste passando.
5. **Revisão e fechamento** — `superpowers:requesting-code-review` e
   `superpowers:verification-before-completion` (rodar os testes de verdade antes de dizer que
   está pronto), depois PR.

A spec é um documento vivo: se a implementação descobrir algo (como aconteceu com Humble →
Foxy), atualize a spec no mesmo PR.

## 4. Convenções de código e git

- **Branch por feature**, PR para `master`. Nada direto na `master`.
- **Commits** em inglês, no formato `tipo: descrição` (`feat:`, `fix:`, `docs:`, `chore:`),
  dizendo o *porquê* quando não for óbvio.
- **CI** (`.github/workflows/`) roda os testes puros em Python 3.8, 3.10 e 3.12 — tem que passar.
- **Python 3.8** é o do robô: todo módulo começa com `from __future__ import annotations`
  (`tests/test_future_annotations.py` cobra) e nada de sintaxe 3.9+ em runtime.
- **`core/` é puro**: não importa `rclpy`, `vision_msgs`, `cv_bridge` nem SDK da Unitree. ROS
  fica em `ros2_ws/`, hardware atrás de uma fronteira fina que dá para trocar por um fake nos
  testes.
- **Testes novos sem hardware** entram em `tests/` e já são pegos pela CI. Teste que precisa de
  modelo/câmera/robô fica fora da CI e é documentado na spec.
- **Código mínimo**: sem abstração para um caso só, sem config para valor que nunca muda.
- **Dados pessoais** (fotos em `data/known_faces/`, bancos `identity_db_*`) nunca vão para o
  git — é dado biométrico (LGPD).

## 5. Robô (Unitree G1 EDU)

O robô é **compartilhado** com outros projetos. Antes de qualquer coisa nele, leia
[`docs/guides/jetson-deployment.md`](docs/guides/jetson-deployment.md), principalmente as
regras de convivência:

- tudo nosso fica em `~/ipe-2-code`; `pip install` só dentro do nosso venv;
- não pare, edite ou desative serviços de outros projetos sem falar com o dono;
- dois programas comandando o mesmo atuador (braço, **alto-falante**) ao mesmo tempo é
  problema — combine antes.

Subir o reconhecimento no robô: `~/ipe-2-code/scripts/robo_tmux.sh && tmux attach -t face`.

**Cadastrar uma pessoa:** no **notebook**, nunca no robô — as fotos não ficam lá, e o enroll
refaz o banco a partir da pasta inteira (rodá-lo no robô apagaria todo mundo). Foto em
`data/known_faces/<nome>/`, enroll aqui, `scp` só do `data/identity_db_*` e reiniciar o nó
(passo 5 do [guia do robô](docs/guides/jetson-deployment.md#5-modelos-e-cadastro)).

## 6. Próxima feature: voz (TTS, microfone e alto-falante)

Ainda **sem spec** — o primeiro passo é o brainstorming (seção 3), gerando
`docs/superpowers/specs/AAAA-MM-DD-voz-design.md`. Ponto de partida levantado no SDK
(`unitree_sdk2_python/unitree_sdk2py/g1/audio/`, exemplos em `example/g1/audio/`):

**O que o G1 oferece** (serviço RPC `voice`, via `AudioClient` do `unitree_sdk2py`, por DDS
na `eth0`):

| Recurso | API | Observações |
|---|---|---|
| TTS embarcado | `TtsMaker(texto, speaker_id)` | Exemplo oficial só em chinês — **testar se fala português** |
| Tocar áudio próprio | `PlayStream(app_name, stream_id, pcm)` / `PlayStop(app_name)` | PCM **16 kHz, mono, 16 bits** (o exemplo de WAV recusa outro formato) |
| Volume | `GetVolume()` / `SetVolume(0–100)` | |
| LED da cabeça | `LedControl(R, G, B)` | Útil como feedback "estou ouvindo/falando" |
| Microfone | UDP multicast `239.168.123.161:5555` | PCM 16 kHz mono 16 bits, entrar no grupo pela interface `192.168.123.x` (exemplo C++ `g1_audio_client_example.cpp`) |
| ASR embarcado | API `1002` + tópico DDS `rt/audio_msg` | Não exposto no cliente Python — investigar |

O `unitree_sdk2py 1.0.1` já está no Python global do robô; o nosso venv
(`--system-site-packages`) enxerga.

**Perguntas que a spec precisa responder:**

- **TTS embarcado ou nosso?** `TtsMaker` é zero dependência, mas pode não ter voz em
  português. A alternativa é sintetizar com Piper (offline, roda na Jetson) e tocar via
  `PlayStream`.
- **Convivência:** o projeto `~/hhhh` já usa voz (Piper + Whisper + caixa Bluetooth). Falar com
  o autor: usamos a mesma caixa ou o alto-falante do robô? Quem tem a vez de falar?
- **Precisa ouvir já?** Se a Fase 2 é "reconhecer → cumprimentar → continência", talvez só TTS
  baste agora e o microfone (ASR) fique para depois.
- **Interface:** um nó ROS2 que assina um tópico de texto (ex.: `/voice/say`, `std_msgs/String`)
  e fala, para o reconhecimento só publicar "Bom dia, general"? Ou chamada direta?
- **Testes sem robô:** a lógica (fila de falas, conversão para PCM 16 kHz, frases por
  identidade) em módulo puro testado na CI; o `AudioClient` atrás de uma fronteira fina com fake.
- **Privacidade:** áudio do microfone é dado pessoal — gravar ou não, e por quanto tempo.

Sugestão de divisão: uma pessoa prova no robô o que `TtsMaker` e `PlayStream` fazem (script
de 10 linhas, sem nó); outra escreve a spec com o resultado; depois plano e execução.
