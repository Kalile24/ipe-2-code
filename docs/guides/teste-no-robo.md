# Mover e testar o robô — passo a passo

Para testar no G1 o que ainda não rodou no robô: a ação `/reaction/rotina`, os estágios, virar e
andar até a pessoa e os combos do controle. Vá na ordem: cada etapa só depois da anterior dar certo.
Specs: [`2026-11-04-aproximacao-e-estagios-design.md`](../superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md)
e [`2026-10-29-rotina-cumprimento-design.md`](../superpowers/specs/2026-10-29-rotina-cumprimento-design.md).
Instalação e ambiente: [`jetson-deployment.md`](jetson-deployment.md). Uso do dia a dia: [`operar-o-robo.md`](operar-o-robo.md).

**Sempre:** alguém com o controle da Unitree na mão; espaço livre em volta; ninguém apertando
START nem F1+… (são do `~/hhhh`). Avise o autor do `~/hhhh` antes dos testes armados.

## Paradas

| Situação | Como parar |
|---|---|
| Robô **no suporte** | Enter na janela `emergencia` (damp: motores soltos, fica pendurado) |
| Robô **fora do suporte** | **F3+DOWN** (para de andar na hora, braços voltam, fica em pé) ou o próprio controle da Unitree. **Nunca damp fora do suporte**: ele cai |
| Qualquer um | Ctrl+C na janela `rotina` (termina o passo atual, para de andar, devolve os braços) |

## 0. Medir o giro (antes de armar a meia-volta)

Só leitura: o script lê o yaw do IMU e **não manda nenhum comando** ao robô.

```bash
cd ~/ipe-2-code && python3 scripts/robo_medir_giro.py          # --interface eth0 é o padrão
```

Imprime, a ~10 Hz, o `yaw` em graus e o `girado` acumulado (+ = esquerda). Robô em pé, **pelo
controle da Unitree**:

- Gire ~180° à **esquerda**: o `girado` tem que chegar perto de **+180**. À **direita**: perto de **-180**.
  Sinal trocado = não arme a meia-volta; mande a medição.
- Parado por 30 s: o `girado` tem que variar **bem menos que 10°** (a tolerância da meia-volta).

Ctrl+C para sair. Só então a meia-volta: veja a seção 9.

## 1. Atualizar e compilar

```bash
cd ~/ipe-2-code && git pull
source scripts/ambiente_robo.sh
cd ~/ipe-2-code/ros2_ws && python3 -m colcon build --symlink-install
systemctl --user restart ipe-controle ipe-painel
```

Tem que terminar com `3 packages finished`. O `robot_reaction_interfaces` é o primeiro pacote em
C/CMake do projeto: se falhar, quase sempre falta algo do rosidl visível para o Python do venv
(`empy`, `lark`, cabeçalhos do numpy). Mande a mensagem de erro.

## 2. Conferir os botões do controle (sem mexer no robô)

```bash
grep -n "0x80\|>> 7\|F2\|F3" ~/hhhh/*.py         # o ~/hhhh já usa esse botão? Se usar, troque os combos
python3 ~/ipe-2-code/scripts/robo_controle.py --mostrar
```

Aperte F3, UP, RIGHT, DOWN e LEFT, um de cada vez: tem que aparecer `0x0080`, `0x1000`, `0x2000`,
`0x4000` e `0x8000`. Ctrl+C para sair. Valores
diferentes: use `--iniciar/--agora/--automatico/--parar` com as máscaras certas.

## 3. Desarmado: reconhecimento, fala e calibrar a caixa

O robô **não se mexe** desarmado.

```bash
~/ipe-2-code/scripts/robo_rotina_cumprimento.sh && tmux attach -t rotina
```

- Janela `deteccoes`: o Gil aparece com nome e nota quando fica na frente.
- Janela `status`: `virar:`/`aproximar: desvio=… caixa=…px vx=… vyaw=…` por ~2 s (só medindo), depois
  a rotina com as posturas como `dry_run` e a fala pela caixa.
- **Escolher a distância de parada:** o Gil fica parado onde o robô deve parar. Leia o `caixa=…px`
  no status; esse número vai em `altura_caixa_alvo_px` (passo 3a).
- **Sentido do giro:** com o Gil à **direita** da imagem, `desvio` sai **positivo** e `vyaw`
  **negativo** (virar à direita). Confirme no passo 5 que o robô vira para o lado dele; se virar
  para o outro, `inverter_giro: true`.
- `scripts/robo_liberar_cumprimento.sh gil` cumprimenta de novo sem esperar 5 min.

### 3a. Seus valores

```bash
cp ~/ipe-2-code/ros2_ws/src/robot_reaction_ros/config/operacao.yaml ~/operacao.yaml
nano ~/operacao.yaml        # altura_caixa_alvo_px, vx, vyaw_max...
OPERACAO=~/operacao.yaml ~/ipe-2-code/scripts/robo_rotina_cumprimento.sh ...
```

Para o primeiro teste andando, comece devagar: `vx: 0.1`, `vyaw_max: 0.2`.

## 4. Armado no suporte, sem andar

Robô no suporte, em damp (ou já em equilíbrio). Só braços e fala:

```bash
~/ipe-2-code/scripts/robo_rotina_cumprimento.sh --armado --estagios fala,posturas
```

Responda `s` à pergunta do suporte. Confira: inicializa (~16 s) → `pronto` → o Gil aparece → a
rotina dele inteira (sentido, continência, fala, desc_arma, à vontade). Depois, de novo, e
**Ctrl+C no meio da rotina**: tem que terminar o passo atual, fazer o à vontade e encerrar.

## 5. Fora do suporte: só virar

Ponha o robô em pé e em equilíbrio **pelo controle**, fora do suporte. Suba sem perguntar pelo
suporte e só com virar e falar:

```bash
~/ipe-2-code/scripts/robo_rotina_cumprimento.sh --controle --estagios virar,fala
```

O `--controle` sobe com as reações automáticas **desligadas**: aperte **F3+RIGHT** (ou rode
`ros2 param set /reaction_node cumprimentar_agora agora`) com o Gil um pouco para o lado. O robô
tem que girar no lugar até ficar de frente e então falar. Se girar para o lado errado: F3+DOWN,
`inverter_giro: true` no seu `operacao.yaml`, e de novo.

Se o robô não estava em equilíbrio, ele fala "Não estou em equilíbrio, não vou começar." e não faz
nada: ponha-o em equilíbrio pelo controle e suba de novo.

## 6. Fora do suporte: andar até a pessoa

```bash
OPERACAO=~/operacao.yaml ~/ipe-2-code/scripts/robo_rotina_cumprimento.sh --controle --estagios virar,aproximar,fala
```

O Gil a ~3 m, de frente para o robô. F3+RIGHT: o robô vira, anda devagar e para quando a caixa do
rosto chega a `altura_caixa_alvo_px`; então fala. Confira também:

- **F3+DOWN no meio da caminhada**: para na hora.
- **O Gil sai da frente** no meio: para em 1 s (`perda_rosto_s`) e desiste em 10 s (`desistir_s`),
  sem cumprimentar (`desistiu: rosto perdido` no status).
- Parou longe ou perto demais: ajuste `altura_caixa_alvo_px` (maior = para mais perto).

Só depois disso, a rotina completa andando: `--estagios virar,aproximar,fala,posturas` (ou sem
`--estagios`).

## 7. Pelo controle, sem terminal

Instale o serviço **só depois de combinar com quem usa o robô** (ele fica de pé desde o boot):

```bash
mkdir -p ~/.config/systemd/user
cp ~/ipe-2-code/scripts/systemd/ipe-controle.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now ipe-controle
sudo loginctl enable-linger unitree
journalctl --user -u ipe-controle -f        # log dos combos
```

| Combo | Faz |
|---|---|
| F3 + UP | sobe tudo armado (só com o robô em equilíbrio), reações automáticas desligadas: ande com o robô pelo controle |
| F3 + RIGHT | cumprimenta agora quem está sendo reconhecido ("Não reconheço ninguém." se ninguém do mapa) |
| F3 + LEFT | liga/desliga as reações automáticas (o robô fala o estado) |
| F3 + DOWN | para e encerra |

Teste na ordem: F3+UP (o log mostra a sessão subindo; `tmux attach -t rotina` mostra as janelas),
F3+RIGHT com o Gil na frente, F3+LEFT duas vezes (ouça "desligadas"/"ligadas"), F3+DOWN.
Para tirar o serviço: `systemctl --user disable --now ipe-controle`.

## 8. Painel web e hotspot

O hotspot tira o robô da rede Wi-Fi em que está e **para a transmissão da D435i do `~/cesar`**
enquanto estiver ligado: combine com eles. O cabo continua funcionando.

```bash
~/ipe-2-code/scripts/robo_hotspot.sh liga          # rede IPE-G1, senha ipe-g1-2026 (HOTSPOT_SENHA troca)
cp ~/ipe-2-code/scripts/systemd/ipe-painel.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now ipe-painel
```

No celular ou notebook, conecte-se à `IPE-G1` e abra `http://10.42.0.1:8080`. Confira:

- Com a rotina parada: faixa **PARADO**, câmera e reconhecimento com `—`.
- **Subir desarmado**: faixa **DESARMADO**; em ~1 min o reconhecimento mostra o ritmo, a webcam mostra o formato real
  (640×480), e quem está na frente aparece com nota, altura e desvio.
- **Pessoas**: com uma foto de teste em **Adicionar às fotos atuais**, a mensagem mostra as aproveitadas e o total. Depois
  disso, copiar o banco do notebook para o robô apaga o que foi cadastrado pelo painel.
- **Calibrar**: siga os 4 passos da distância de parada; depois do **Salvar distância**, o topo avisa do ajuste pendente até
  **PARAR** e subir de novo. Tente salvar `vx` = 2: tem que ser recusado.
- **Sem conexão**: saia do Wi-Fi com o painel aberto. Em ~5 s a faixa vira **SEM CONEXÃO**.
- **Armado andando**: a faixa continua **ARMADO** durante toda a caminhada.
- **Baixar diagnóstico** gera o arquivo de texto.
- **Subir armado** só com o robô em equilíbrio (FSM 801), como o F3+UP.
- `robo_hotspot.sh desliga` volta o robô para a rede de antes.

## 9. Meia-volta

Depois de um cumprimento com sucesso, o robô gira 180° pela **esquerda** (fechado no yaw do IMU), dá
um passo à frente (~0,2 m) e **espera o operador**. Estágio **Meia-volta** no painel; design em
[`2026-11-07-meia-volta-design.md`](../superpowers/specs/2026-11-07-meia-volta-design.md). Só depois do passo zero
(seção 0) e com **espaço**: o passo é cego (sem detecção de obstáculo), deixe ~1 m livre atrás de onde o
robô começa. Operador com o controle na mão.

1. **Desarmado:** a rotina só registra `dry_run meia_volta` no log e também espera o operador.
2. **Primeira meia-volta armada**, com muito espaço, `vyaw_meia_volta` em 0,5 (o padrão): cumprimente
   (F3+RIGHT). Confira: estado "fazendo meia-volta" e giro à esquerda; depois o passo; depois
   "aguardando o operador".
3. **Liberar:** botão **Liberar cumprimentos** no painel, ou desligar e ligar o automático (F3+LEFT duas
   vezes), ou **cumprimentar agora** (só libera se alguém for reconhecido).
4. **PARAR / F3+DOWN no meio do giro e do passo:** têm que parar na hora.
5. Se falhar, o log diz `meia_volta: falhou (tempo esgotado | girou para o lado errado | sem angulo |
   interrompida)`. Se girar para o lado errado ele para sozinho: avise o autor.

Ajustes (grupo **Meia-volta** na aba Calibrar): `vyaw_meia_volta` 0,5 rad/s, `tolerancia_meia_volta_graus`
10°, `passo_m` 0,2 m (0 = sem passo), `vx_passo` 0,2 m/s, `tempo_max_meia_volta_s` 12 s.

### 9a. Retorno ao ponto de partida

Depois da meia-volta, anda até onde estava ao reconhecer a pessoa e vira de frente para ela. Design:
[`2026-11-10-retorno-escuta-painel-design.md`](../superpowers/specs/2026-11-10-retorno-escuta-painel-design.md).

1. **Medir a odometria (só leitura, nenhum comando ao robô):** `python3 scripts/robo_medir_odometria.py`. Marque o chão,
   ande ~1 m pelo controle da Unitree, volte à marca e fique 20 s parado; Ctrl+C mostra o resumo. Tem que dar `andou`
   perto da distância real e `do inicio` < 0,15 m na marca. O `rt/odommodestate` publica neste G1 (o de 20 Hz, `rt/lf/…`,
   não). Se a odometria não acompanhar, não ligue o retorno.
2. **Desarmado:** marque **Retorno** no painel e cumprimente: nada se mexe; o log só não tem erro.
3. **Armado, com espaço:** a pessoa a ~3 m, caminho livre. F3+→: aproxima, cumprimenta, meia-volta, **anda de volta**
   ("retorno: andando (faltam …)") e **vira de frente** ("retorno: virando para a pessoa", "retorno: fim").
4. **F3+↓ no meio da volta e no meio do giro final:** para na hora.
5. Se falhar: `retorno: falhou (tempo esgotado | afastando do ponto de partida | sem odometria | sem ponto de partida |
   interrompida)`. Ajustes no grupo **Retorno** da aba Calibrar (comece com `vx_retorno` 0,2–0,3).

## 10. Comandos de voz

O reconhecimento de fala é o Vosk com a gramática dos comandos (instalação: [`jetson-deployment.md`](jetson-deployment.md)
seção 5). Na subida, a janela `rotina` mostra `reconhecimento de fala: Vosk, 9 frases`. Os comandos (Sentido, Apresentar arma,
Atenção, Apresente-se, Descansar arma, À vontade) também se testam por texto, sem microfone. "Atenção" (descansar) foi
religado em 2026-11-10 depois de duas idas e voltas estáveis no robô.

```bash
cd ~/ipe-2-code/ros2_ws && python3 -m colcon build --symlink-install   # a ação Rotina mudou: build completo
systemctl --user restart ipe-controle ipe-painel
~/ipe-2-code/scripts/robo_medir_voz.sh [dispositivo]           # lista, grava 5 s, mostra tamanho e pico; apaga o arquivo
```

Microfone: o `robo_rotina_cumprimento.sh` usa o dispositivo escrito em `data/microfone.txt` (uma linha, ex.
`plughw:CARD=Intelbras,DEV=0`); sem o arquivo, a placa "Intelbras" do `arecord -l`; sem ela, `default`. A escolha aparece
na subida. Sem microfone, com o robô em equilíbrio e a rotina de pé:

```bash
source ~/ipe-2-code/scripts/ambiente_robo.sh
cd ~/ipe-2-code && python3 -c 'from core.comandos_voz import enviar_voz; enviar_voz("texto:sentido")'
```

Troque `sentido` por `apresentar arma`, `atenção`, `apresente se`, `descansar arma` ou `à vontade`. Confira, no painel e no status:

- [ ] `arecord` existe; `robo_medir_voz.sh` mostra o microfone e um pico acima de zero falando.
- [ ] Segurar F3+Y, dizer "Tenente Nichinica, sentido" e soltar: o log mostra `voz: 'tenente sentido' -> sentido`.
- [ ] Os outros quatro pela voz. Com a pausa militar ("apresentar… arma"), solte só depois do "arma".
- [ ] `texto:sentido`: o painel mostra "segurando sentido"; durante ele, F3+→ toca os dois tons graves de recusado.
- [ ] Com F3+Y segurado, F3+↓ ainda para tudo.
- [ ] Segurando **Apresentar arma**, F3+X e depois F3+↓: observe a folga dos braços (soltar pula o desc. arma).
- [ ] "Tenente Nichinica, apresentar arma" e depois "Tenente Nichinica, descansar arma": o braço desce rápido e o robô
      **fica em sentido** (painel: "segurando sentido") até "à vontade".
- [ ] **Escuta contínua (F3+L1):** dois tons subindo e "Escuta ligada"; o painel mostra ESCUTANDO. Sem apertar nada,
      "Tenente Nichinica, sentido" executa; "sentido" sozinho não. Conversa perto do robô não dispara nada. F3+Y ainda
      funciona. F3+L1 de novo: dois tons descendo e "Escuta desligada". O botão do cartão **Voz** faz o mesmo.
- [ ] **F3+R1**: sentido, a fala de apresentação pela caixa e à vontade. No painel, mude o texto, salve e aperte
      **Fala de apresentação**: tem que sair o texto novo. Ajuste a pronúncia de "Nichinica" e "Níksi" se precisar.
- [ ] F3+X (ou o botão **À vontade**) solta; sem nada, solta sozinho em 300 s (`posicao_max_s`).

## O que falta (atualizado em 2026-11-11)

Testado no robô em 2026-11-10/11: atualização e compilação, medição do giro, meia-volta (tolerância 3°, passo 0,4 m),
caminho completo (aproximação → cumprimento → meia-volta), comandos de voz pelo Vosk, fala de apresentação (F3+R1),
cadastro pela webcam (bianco), retorno ao ponto de partida, escuta contínua, bateria no painel e a aproximação a 0,45 m/s
(confirmada pelo operador).

Falta:

- [ ] **"Descansar arma" pela voz** (seção 10): "Tenente Nichinica, apresentar arma" e depois "Tenente Nichinica,
      descansar arma". O braço tem que descer rápido e o robô ficar **em sentido** até o "à vontade" (ordem unida).

Na próxima conexão ao robô:

- **Instalar o "descansar arma" que mantém o sentido** (`0222a43`): `git pull` (ou o envio por SSH do guia de operação), sem
  build; descer e subir a rotina para o YAML valer. Depois, o teste acima.
- **TensorRT no reconhecimento:** hoje roda só com CUDA porque falta a pasta do cache, e o painel mostra os quadros/s
  **variando muito**. Com o TensorRT, em outubro: ~42 ms por quadro, ~24 quadros/s estáveis. Com a rotina parada:
  `mkdir -p ~/.insightface/trt_cache/buffalo_l`; na primeira subida o reconhecimento fica **~2 min sem processar**
  enquanto o TensorRT monta os engines (normal); as seguintes começam na hora. Confira no log da janela `rotina`:
  `providers ativos` com `TensorrtExecutionProvider` e sem `EP Error ... trt_cache`; no painel, os quadros/s estáveis.

Fica para depois da apresentação de quinta-feira (2026-11-13):

- **LiDAR (Livox MID-360):** ler a nuvem que a Unitree já publica em `rt/utlidar/cloud_livox_mid360` (10 Hz, tipo
  `PointCloud2_`, já no `unitree_sdk2py`: nada a instalar). 1) script só de leitura com a distância do ponto mais próximo à
  frente, conferido com uma pessoa/caixa a 1, 2 e 3 m; 2) **parada por obstáculo** em todas as caminhadas (aproximação,
  meia-volta, retorno): algo numa caixa à frente → para e registra. O `livox_ros_driver2` (direto no IP 192.168.123.120)
  só se o tópico não bastar: disputaria o sensor com o driver da Unitree, que o SLAM usa.
- **Explorar a movimentação** — roteiro completo em [`testar-marcha.md`](testar-marcha.md) (sempre com alguém segurando e o controle na mão): velocidade da aproximação 0,45 × 0,3 m/s
  filmado; modo de caminhada **801 (Run, o atual) × 500 (Walk) × 501 (Walk, cintura 3 eixos)** — trocar pelo controle, no
  suporte; o código exige 801 para armar e só muda se o 500/501 ficar melhor; **passo lateral** (`vy`) para se alinhar
  com a pessoa; gestos do firmware (aperto de mão 27, aceno 26) no cumprimento, coordenando com o `arm_sdk`.
- **Mapeamento (SLAM, serviço `slam_operate`) — teste exploratório:** mapear a sala pelo controle (APIs 1801/1802), ligar
  de novo e conferir se ele se localiza (1804, só leitura), depois ir a um ponto 2 m à frente e voltar (1102). Se for
  preciso, vira o "posto" da apresentação e substitui a odometria no retorno. Doc: `UNITREE_G1_base_documentacao/
  ORIGINAIS/unitree_official_G1_developer/734_slam_navigation_services_interface.md`.
- **Mensagem "inicializando: damp → em pé → equilíbrio (robô no suporte)"** aparece mesmo quando o robô já está em
  equilíbrio e nada é feito: texto que assusta, sem efeito no movimento.
- **Webcam com mau contato no USB:** cai e volta algumas vezes (`usb 1-3: USB disconnect` no `journalctl -k`). Prender o
  conector ou trocar o cabo/porta; o vigia da câmera continua desligado.
- **Testes do pacote ROS mais rápidos** (~2 min): rodar só os arquivos afetados no dia a dia, `--durations` para achar os
  lentos, `pytest-xdist` com um `ROS_DOMAIN_ID` por processo.

## O que mandar se algo der errado

- A janela `status` (o que o body_node fez) e o log da janela `rotina`.
- Da meia-volta: a saída do `robo_medir_giro.py` e a linha `meia_volta:` do status.
- Do retorno: o resumo do `robo_medir_odometria.py` e as linhas `retorno:` do status.
- Da escuta contínua: as linhas `escuta:` do log da janela `rotina` (o que ouviu e o comando).
- Em qual etapa deste guia, com quais `--estagios` e qual `operacao.yaml`.
- O arquivo do **Baixar diagnóstico**, do painel.
- Pelo controle: `journalctl --user -u ipe-controle --since "-10min"`.
- Painel: `journalctl --user -u ipe-painel --since "-10min"`.
