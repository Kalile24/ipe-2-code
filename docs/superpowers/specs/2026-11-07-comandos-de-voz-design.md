# Comandos de voz do operador (Whisper) — Design

Data: 2026-11-07. Independente da meia-volta (`2026-11-07-meia-volta-design.md`). Contexto: rotina de
cumprimento (`2026-10-29-rotina-cumprimento-design.md`), aproximação e estágios
(`2026-11-04-aproximacao-e-estagios-design.md`), painel (`2026-11-04-painel-design.md`).

Objetivo: o operador dá ordens de voz ao robô ("Sentido!", "Continência!") e ele responde com
posturas e falas pré-definidas, como numa ordem unida. Sem conversa e sem LLM: uma lista fixa de
comandos, previsível e rápida.

## Decisões do usuário (2026-11-07)

- **Só o operador fala com o robô**, segurando um botão do controle. A plateia não aciona nada.
- **Microfone da webcam Intelbras** (o embutido do G1 depende do serviço `voice`, que vive caindo).
- **Comandos e respostas:**

  | O operador diz | O robô faz | Depois |
  |---|---|---|
  | "Sentido" | postura sentido | **fica** em sentido |
  | "Continência" | continência | **fica** em continência |
  | "Atenção" | descansar | **fica** em descansar |
  | "Apresentação" | sentido → fala "Sou o Tenente Nixinica" (escrita para o Piper: "Nichinica") → à vontade | volta a poder andar |
  | "À vontade" | à vontade (braços de volta, solta o `arm_sdk`) | volta a poder andar |

- **Posição mantida até o à vontade**, por voz ou por um botão do controle.
- **Não entendeu, ou a frase não é comando:** não se mexe e fala "Não entendi, repita o comando".
- **Voz e cumprimento automático não podem disputar o corpo.** Um comando que chega durante um
  cumprimento é recusado (nada se mexe). A política geral de prioridades entre todas as ações fica
  para um projeto próprio (gerenciar as ações e aprimorar o painel).

## Comportamento

1. O operador **segura** o combo de falar, diz o comando e solta. Gravação de no máximo ~5 s; soltar
   encerra.
2. O áudio vai para o Whisper local (português). O texto reconhecido aparece no painel e no log.
3. O texto é comparado com a tabela de comandos (sem acento, sem pontuação, sem diferença de
   maiúsculas; "Tenente, sentido!" vale como "sentido"). Uma frase que bate com dois comandos, ou
   com nenhum, é "não entendi".
4. O robô executa a resposta. As de **posição mantida** deixam os braços na pose e o `arm_sdk`
   ligado até o à vontade. De uma posição mantida para outra (sentido → continência), vai direto,
   sem passar pelo à vontade.
5. **Enquanto mantém uma posição, o cumprimento automático fica suspenso.** Volta ao normal com o à
   vontade. A suspensão fica no `reaction_node` (escolha do Claude): ele não tenta cumprimentar
   durante a posição mantida, em vez de mandar e ter a rotina recusada a cada quadro (o `forget` da
   recusa faria ele insistir sem parar). Quem foi visto nesse meio-tempo não conta como
   cumprimentado; depois do à vontade valem as regras de sempre. O "cumprimentar agora" (F2+RIGHT e
   painel) também é recusado durante a posição mantida.

**Desarmado ou não inicializado:** igual às rotinas de hoje: as posturas só vão para o log
(`dry_run`), mas as falas saem de verdade. Assim dá para testar microfone → Whisper → comando → fala
sem armar o robô. Escolha do Claude.

**Recusado (nada se mexe, o painel mostra o motivo):** rotina de cumprimento em andamento, ou o robô
ainda falando a resposta anterior. A recusa é **silenciosa** (decisão do usuário, 2026-11-08): o robô não
fala nada, só o painel avisa.

## Decisões de implementação (escolhas do Claude, o usuário pode mudar)

- **Combos do controle**, no `core/remote_combos.py`, sem repetir os que existem nem os F1+… do
  `~/hhhh`. O botão é o que os guias chamam de **F3** (bit `0x80`, `F2` no código):
  - **F3 + Y, segurado:** fala (grava enquanto estiver apertado).
  - **F3 + X:** à vontade.
  O `robo_controle.py` já lê o controle; ele passa a detectar também o **soltar** do F3+Y e avisa o
  nó de voz por um datagrama UDP local (`ros2 param set` levaria ~1 s e cortaria o começo da fala).
- **Tabela de comandos num YAML** (`config/comandos_voz.yaml`): palavras-chave → passos, no mesmo
  formato de passos do `reactions.yaml` (`postura`, `fala`, `pausa`). A posição é mantida quando
  a última postura não é `a_vontade`. O texto de "não entendi" fica no mesmo arquivo.
- **Whisper:** primeiro tentar o que já está no robô (a imagem `openvoice-piper-whisper-jetson:1.0`,
  usada pelo `scripts/robo_voz.sh` só para o Piper), num contêiner nosso como o `ipe-piper`. Se o
  modelo de lá não servir para português ou for lento, faster-whisper `small` multilíngue, int8.
  Modelos `.en` não servem. A escolha final sai da medição do passo zero.
- **Execução pelo `body_node`**, que já é o único dono dos braços e das pernas e só aceita uma
  rotina por vez. A posição mantida é um estado novo do `body_node`; a regra "toda rotina termina em
  `a_vontade`" (`validate_steps`) continua valendo para o `reactions.yaml` e para a "Apresentação".
- **O PARAR (painel, F2+DOWN, Ctrl+C) continua acima de tudo:** sai da posição mantida com à vontade
  e encerra, como hoje.

## Segurança

- **A voz nunca move as pernas.** Os comandos só têm posturas de braço e falas. **Exceção conhecida:**
  o descansar ("Atenção") dá hoje um passo curto para frente (`passo_descansar`, impulso de
  `SetVelocity` de 0,12 m/s) para compensar os braços indo para trás. Fica assim por enquanto.
- **Pendente: o descansar desequilibra o robô para trás** quando os braços vão para trás (relato do
  usuário, 2026-11-07). A inclinação do tronco que deveria compensar (+0,20 rad de `WaistPitch`) tem o
  sinal certo segundo o URDF oficial (eixo +y, positivo = para frente; o comentário do código está
  errado). Suspeita principal: o **fixador da cintura** do G1-EDU 29 DoF, que trava a inclinação e a
  rolagem e faz o comando não ter efeito (exemplo oficial `g1_arm7_sdk_dds_example.py`; doc
  `300_waist_fastener.md`). Confirmar olhando o robô/app ou o aviso "estágio 2 de Descansar não
  convergiu" no log. O "Atenção" só vai para o robô depois disso resolvido.
  **Atualização 2026-11-10:** no robô, "Atenção" e depois "À vontade", duas vezes, com o operador segurando: estável na ida
  e na volta, todos os estágios convergiram (sem aviso) e o `WaistPitch` de 0,20 rad foi aplicado. O fixador não estava
  travando. O "Atenção" foi religado.
- Posturas só com o robô armado e inicializado; desarmado, só log (as falas saem).
- **Sem escuta contínua:** só grava com o combo apertado. Não grava enquanto o robô fala.
- **O áudio não é gravado em disco.** Só o texto reconhecido vai para o log e para o painel.
- Comando ambíguo ou desconhecido não faz nada além da fala "Não entendi, repita o comando".
- Manter a continência por muito tempo aquece o ombro: tempo máximo numa posição mantida (ex.:
  5 min; depois disso, à vontade sozinho e aviso no painel). Escolha do Claude; o valor sai do teste.

## Painel

- Último texto ouvido, o comando entendido (ou "não entendi") e o tempo da transcrição.
- O estado "segurando sentido / continência / descansar".
- Botão **À vontade**.
- Aviso se o microfone da webcam sumiu.

## Passo zero: medição no robô (antes do código)

Tudo só de leitura ou em contêiner nosso, com o usuário por perto (o robô é compartilhado):

- A webcam Intelbras aparece como placa de captura (`arecord -l`)? Formato e taxa.
- Gravar o operador a 1–2 m dizendo os cinco comandos, com o robô em pé (ventoinhas e motores
  ligados). Transcrever no robô e anotar acertos e tempo.
- O Whisper da imagem existente: qual modelo, aceita português, quanto tempo leva com o
  reconhecimento facial rodando ao mesmo tempo (CPU e GPU).
- Os gravados de teste são apagados depois da medição.

## Testes

- Puros: comparação de texto com a tabela (acentos, pontuação, frase com dois comandos, frase vazia),
  validação do YAML, a máquina de estados da posição mantida (manter, trocar, à vontade, PARAR,
  tempo máximo, recusa durante cumprimento).
- ROS: o `body_node` recusa voz durante cumprimento; o cumprimento automático fica suspenso enquanto
  há posição mantida.
- No robô: roteiro em `docs/guides/teste-no-robo.md`; o guia de operação explica os combos novos e os
  comandos.

## Fora do escopo

Conversa com LLM, perguntas e respostas sobre o Nixinica, palavra de ativação, comandos da plateia,
comandos que movem as pernas (ex.: meia-volta por voz), microfone embutido do G1.
