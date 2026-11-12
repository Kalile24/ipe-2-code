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
cd ros2_ws && python3 -m colcon build --symlink-install
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

## O que mandar se algo der errado

- A janela `status` (o que o body_node fez) e o log da janela `rotina`.
- Da meia-volta: a saída do `robo_medir_giro.py` e a linha `meia_volta:` do status.
- Em qual etapa deste guia, com quais `--estagios` e qual `operacao.yaml`.
- O arquivo do **Baixar diagnóstico**, do painel.
- Pelo controle: `journalctl --user -u ipe-controle --since "-10min"`.
- Painel: `journalctl --user -u ipe-painel --since "-10min"`.
