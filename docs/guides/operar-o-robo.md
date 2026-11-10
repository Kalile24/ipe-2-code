# Operar o robô: guia completo

Tudo o que é preciso para usar o G1: atualizar, ligar, operar pelo controle e pelo celular, cadastrar
pessoas, trocar webcam ou caixa, e resolver problemas.

> **Fora do suporte, nunca dê damp (F3+B): os motores soltam e o robô cai.**
> Para parar fora do suporte: **F3+↓** ou o botão **PARAR** do painel.

**Sempre:** alguém com o controle na mão e espaço livre em volta. Ninguém aperta START nem F1+… (são
do `~/hhhh`).

## 1. Atualizar o robô

### Entrega dos testes finais (2026-11-05): o que instalar

Código e guias: branch `master`, no GitHub. **Fotos e bancos de rostos não estão no GitHub, e não devem entrar:**
o repositório é público e são dados biométricos. Vêm no pacote `ipe-g1-dados-robo-2026-11-05.tar.gz`, que o responsável entrega por canal
privado; apague suas cópias depois de instalar.

| No pacote | Vai para o robô? | Para que serve |
|---|---|---|
| `data/identity_db_buffalo_l.npz` e `.json` (`956ef5a8e35a5797…`, `a4b75646e3614d46…`) | **Sim, obrigatório** | Banco de rostos do modelo padrão: Aderson 6 fotos, Gil 2 |
| `data/identity_db_buffalo_sc.npz` e `.json` (`08927c876a8b03c7…`, `a4b75646e3614d46…`) | **Sim** | O mesmo banco para o modelo `buffalo_sc` |
| `data/identity_db_buffalo_s.*` | Não | Reserva, para o modelo `buffalo_s` |
| `data/known_faces/{gil,aderson}/` | **Não** | Fotos brutas: ficam fora do robô e só servem para refazer o banco com `apps.enroll` |
| `SHA256SUMS` | Não | Confere o pacote inteiro |

Pacote: SHA-256 `851a45877e6f700fd7c01e3bcbfb40f907ceebe351ee93ef62fe8b2286d01a8b`. No robô precisam existir, de instalações anteriores: `~/.insightface/models/buffalo_l`, o `.venv` e o
`~/unitree_sdk2_python` ([`jetson-deployment.md`](jetson-deployment.md)). Sem eles, pare e instale antes. O modelo
`buffalo_sc` só é necessário para quem for usá-lo; a rotina usa `buffalo_l`.

**Antes:** rotina parada (F3+↓ ou PARAR) e combinado com quem usa o robô. Use o IP que estiver disponível: cabo
`192.168.123.164`, hotspot `10.42.0.1` (derruba a transmissão da D435i do `~/cesar`) ou o IP do Wi-Fi.

**1. No robô, veja o que existe:** `cd ~/ipe-2-code && git status && git branch --show-current && ls -la data/`. Se
houver alteração local que não seja sua, pare e pergunte. Guarde o banco atual:
`mkdir -p ~/banco-antes && cp data/identity_db_* ~/banco-antes/`.

**2. Código.** Com internet no robô:

```bash
cd ~/ipe-2-code && git fetch --prune origin && git switch master && git pull
```

Sem internet no robô, de um computador com o repositório atualizado (`git fetch origin` antes):

```bash
ROBO=unitree@IP_DO_ROBO
git push ssh://$ROBO/home/unitree/ipe-2-code master:refs/heads/entrega \
  origin/backup/robo-ultimo-teste-fisico:refs/heads/backup/robo-ultimo-teste-fisico
```

e depois, no robô. O `stash` guarda as alterações locais, sem perdê-las; só é preciso se o `git status` mostrar alguma:

```bash
cd ~/ipe-2-code
git -c user.name=robo -c user.email=robo@local stash push -u -m "antes da entrega"
git switch master && git merge --ff-only entrega
```

**3. Banco de rostos.** Do computador com o pacote, e depois no robô:

```bash
scp ipe-g1-dados-robo-2026-11-05.tar.gz $ROBO:/tmp/
```

```bash
mkdir /tmp/g1 && tar -xzf /tmp/ipe-g1-dados-robo-2026-11-05.tar.gz -C /tmp/g1
(cd /tmp/g1 && sha256sum -c SHA256SUMS --quiet) && echo PACOTE_OK     # sem PACOTE_OK, pare
cp /tmp/g1/data/identity_db_buffalo_l.* /tmp/g1/data/identity_db_buffalo_sc.* ~/ipe-2-code/data/
rm -rf /tmp/g1 /tmp/ipe-g1-dados-robo-2026-11-05.tar.gz      # as fotos não ficam no robô
```

Isso substitui o banco: quem foi cadastrado antes pelo painel deixa de ser reconhecido. Se o `data/` do robô tiver
`reactions.yaml`, veja se as pessoas ainda valem.

**4. Compilar, limpar e reiniciar.** Compilar é obrigatório: o `Cadastrar.srv` mudou.

```bash
cd ~/ipe-2-code && source scripts/ambiente_robo.sh
cd ros2_ws && python3 -m colcon build --symlink-install    # tem que terminar com "3 packages finished"
cat ~/ipe-2-code/data/operacao.yaml; rm -f ~/ipe-2-code/data/operacao.yaml    # tira ajustes antigos, que venceriam os novos
cat ~/ipe-2-code/data/reactions.yaml 2>/dev/null
systemctl --user restart ipe-controle ipe-painel
```

Se os serviços ainda não existirem, veja logo abaixo como instalar.

**5. Conferir.** No painel, **Pessoas** mostra aderson com 6 fotos e gil com 2, ambos com rotina. Ligue **uma** webcam (a
Intelbras está em teste; seção 6), **Subir desarmado**, e confira em **Operar** o formato 640×480 e o reconhecimento. Depois,
calibre a distância (seção 7) e siga [`teste-no-robo.md`](teste-no-robo.md). Para voltar ao banco anterior: `~/banco-antes`.

### Atualização comum

```bash
cd ~/ipe-2-code && git status      # não pode haver alteração local; se houver, resolva antes
git fetch --prune origin && git switch master && git pull
source scripts/ambiente_robo.sh
cd ros2_ws && python3 -m colcon build --symlink-install    # tem que terminar com "3 packages finished"
cat ~/ipe-2-code/data/operacao.yaml; rm -f ~/ipe-2-code/data/operacao.yaml    # tira ajustes antigos, que venceriam os novos
```

Instalar ou reiniciar os serviços (se ainda não existem, combine antes com quem usa o robô):

```bash
mkdir -p ~/.config/systemd/user
cp ~/ipe-2-code/scripts/systemd/ipe-controle.service ~/ipe-2-code/scripts/systemd/ipe-painel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ipe-controle ipe-painel
systemctl --user restart ipe-controle ipe-painel
sudo loginctl enable-linger unitree
```

Hotspot. **Enquanto ligado, o robô sai do Wi-Fi em que estava e a transmissão da D435i do `~/cesar`
para:** combine antes. O cabo continua funcionando.

```bash
~/ipe-2-code/scripts/robo_hotspot.sh liga        # cria e liga a rede IPE-G1
~/ipe-2-code/scripts/robo_hotspot.sh boot-liga   # opcional: liga sozinho a cada boot
```

Depois: `robo_hotspot.sh estado`, `desliga` (volta ao Wi-Fi anterior) ou `boot-desliga`.

### Se a versão nova der problema: voltar ao último teste físico

```bash
cd ~/ipe-2-code && git switch backup/robo-ultimo-teste-fisico    # sem essa branch no robô: `git fetch origin` antes, ou envie como na seção acima
source scripts/ambiente_robo.sh && cd ros2_ws && python3 -m colcon build --symlink-install
systemctl --user restart ipe-controle ipe-painel
```

Para retornar: `git switch master`, compile e reinicie do mesmo jeito. Fotos e ajustes em `data/` não
são afetados. Essa versão não tem o aviso de voz, a rotina do Aderson nem os recursos novos do painel.

## 2. Ligar e conectar

1. Webcam ligada no USB **antes** de subir a rotina. Caixa de som ligada (sem ela, o robô funciona sem fala nem bipes).
2. No celular, entre na rede **`IPE-G1`**, senha **`ipe-g1-2026`**. Se avisar que não há internet, continue conectado.
3. Abra **`http://10.42.0.1:8080`**. A faixa no topo diz se está tudo pronto ou o que falta.

Pôr o robô em equilíbrio (FSM 801): pelo controle da Unitree, ou, **no suporte e em damp**, segurando **F3+A** por 1,5 s.

## 3. Controle

Segure **F3** e aperte o outro botão.

| Combo | O que faz | Bipe |
|---|---|---|
| **F3 + ↑** | Sobe a rotina armada, com o automático **desligado**. Só em equilíbrio | dois tons subindo |
| **F3 + →** | Cumprimenta agora quem está sendo reconhecido | um tom |
| **F3 + ←** | Liga/desliga o automático (o robô fala o estado) | dois tons iguais |
| **F3 + ↓** | **Para:** velocidade zero, braços de volta, encerra. Também aborta um F3+A | tom grave; dois descendo ao encerrar |
| **F3 + A** (segurar 1,5 s) | Levanta **no suporte**. Só com o robô mole | três bipes curtos ao começar |
| **F3 + B** (segurar 1,5 s) | **Damp. Só no suporte.** Recusado com a rotina de pé | três curtos; três descendo |
| **F3 + Y** (segurar e falar, até 8 s) | Grava o comando de voz; ao soltar, o robô o executa. Recusado enquanto uma rotina roda; com o nó de voz fora do ar, nada acontece | sem bipe |
| **F3 + X** | **À vontade:** solta a posição mantida por voz (o mesmo do botão **À vontade** do painel) | |
| **F3 + L1** | **Escuta contínua de voz:** liga/desliga. O robô ouve sem apertar nada, só frases que começam por "Tenente…" | dois tons subindo + "Escuta ligada"; dois descendo + "Escuta desligada" |
| **F3 + R1** | **Fala de apresentação:** sentido, o texto e à vontade (o mesmo do botão **Fala de apresentação**). Recusado enquanto uma rotina roda | |

**Dois tons graves = recusado:** nada aconteceu. O L2+B da Unitree não dá damp no modo de equilíbrio.

### Comandos de voz

Segure **F3+Y**, fale perto do microfone da webcam e solte **só depois de terminar a frase** (a gravação para
sozinha em 8 s). Pode usar o vocativo ("Tenente Nichinica, sentido") ou só o comando ("sentido").

| Diga | O robô faz |
|---|---|
| **Sentido** | Posição de sentido e **mantém** |
| **Apresentar arma** (ou só "apresentar") | Continência e **mantém** |
| **Atenção** | Descansar e **mantém** |
| **Apresente-se** | Sentido, "Sou o Tenente Nichinica" e à vontade |
| **Descansar arma** | Depois do apresentar arma: abaixa o braço rápido (como na rotina de cumprimento) e fica à vontade |
| **À vontade** | Solta a posição (também **F3+X** e o botão **À vontade**) |

**Escuta contínua** (F3+L1 ou **Ligar escuta contínua** no cartão **Voz** do painel): o robô ouve o tempo todo, sem
apertar nada, mas **só aceita frases que começam por "Tenente"** ("Tenente Nichinica, sentido"): "sentido" solto, vindo da
plateia, não dispara. Ao ligar: dois tons subindo e "Escuta ligada"; ao desligar, dois descendo e "Escuta desligada"; o
painel mostra **ESCUTANDO**. Não ouve enquanto um cumprimento ou um comando está em andamento (o robô pode estar falando)
nem 1 s depois. O F3+Y continua funcionando com a escuta ligada. Começa **desligada** a cada subida; PARAR desliga.

**Fala de apresentação** (F3+R1 ou o botão no painel): sentido, "Olá oficiais, alunos e banca avaliadora, sou o Tenente
Nichinica, o robô humanoide do projeto Níksi." e à vontade. Edite o texto no painel (aba **Operar**, **Ordens**, "Texto da
fala de apresentação"), escrito como deve soar; vale na próxima fala. Fica em `data/discurso.txt`.

O reconhecimento é o **Vosk** com uma gramática: ele só ouve as frases da tabela, então ou acerta o comando ou
responde "Não entendi" (nunca inventa outro). Roda na CPU, dentro do nó de voz, e decide em ~0,1 s depois de soltar.

A posição mantida só termina com **à vontade**, **PARAR** (F3+↓) ou após 300 s (`posicao_max_s`). Durante ela, o
cumprimento automático e o **cumprimentar agora** (F3+→) são recusados (o F3+→ toca os dois tons graves de recusado; o automático recusa em silêncio). O cartão **Voz**
mostra a última frase, o resultado e "segurando <postura>"; sem microfone, avisa na faixa de problemas. Palavras e
passos: `ros2_ws/src/robot_reaction_ros/config/comandos_voz.yaml`. Microfone: o `robo_rotina_cumprimento.sh` usa o
dispositivo ALSA escrito (uma linha) em `data/microfone.txt`; sem o arquivo, a placa "Intelbras" do `arecord -l`
(`plughw:CARD=<id>,DEV=0`); sem ela, `default`. Ele mostra a escolha ao subir. Meça com `scripts/robo_medir_voz.sh [dispositivo]`.
**"Atenção"** (descansar) foi religado em 2026-11-10: duas idas e voltas no robô ficaram estáveis, sem o tombo para trás
de 07/11. Nos primeiros usos, fique perto do robô na saída do descansar.

Sem o modelo do Vosk instalado (`~/.cache/ipe-vosk`, [`jetson-deployment.md`](jetson-deployment.md) seção 5), o nó de voz
registra "reconhecimento de fala desligado" e todo comando falado responde "Não entendi".

### Uso normal

1. Com o robô em equilíbrio, **F3+↑**. Em cerca de 1 min, o painel mostra o reconhecimento no ar.
2. **Manual:** pessoa na frente, **F3+→**. **Automático:** **F3+←** uma vez.
3. O robô vira, anda até a pessoa, para e faz o gesto: sentido → continência → fala → desc. arma → à vontade.
4. Ao terminar, **F3+↓**. Espere os dois tons descendo antes de subir de novo.

## 4. Painel

Sempre visíveis: **PARAR**, se há conexão, e a faixa com o estado (**PARADO**, **DESARMADO** ou **ARMADO**) e o
estágio. Logo abaixo aparecem os problemas, em vermelho. Sem resposta do robô por 5 s, a faixa vira
**SEM CONEXÃO** e a tela fica apagada: o que aparece é antigo, e para parar use o controle.

| Aba | Para que serve |
|---|---|
| **Operar** | Estado de webcam (nome, formato real, quedas), câmera, reconhecimento e caixa; comandos e ordens (Sentido, Continência, Apresentação, À vontade); o que o robô faz ao cumprimentar (marcar e desmarcar vale já; recusado durante uma rotina); quem está na frente, com nota, altura do rosto e desvio; **Eventos** e **Baixar diagnóstico** |
| **Calibrar** | Passo a passo da distância de parada e os demais ajustes (seção 7) |
| **Pessoas** | Quem tem foto e rotina, **Remover** e cadastro (seção 5) |
| **Sistema** | Testar e trocar a caixa (seção 6) e o **Log técnico**: estado, ajustes, eventos e a janela `rotina` do tmux |

**PARAR** faz o mesmo que F3+↓ com a rotina de pé. Duas exceções, em que o painel avisa o que fazer: um levantar
(F3+A) em andamento só para pelo controle, e uma rotina iniciada à mão só para com Ctrl+C no terminal dela.

**Eventos** junta linhas repetidas (`×42`) e abre uma nova quando o estado muda. Se a subida falhar, o motivo
aparece em vermelho no topo. **Baixar diagnóstico** gera um arquivo de texto para investigar sem cabo.

**Rede:** o painel não tem login e atende em todas as redes do robô. Pedidos vindos de outros sites são recusados,
mas quem estiver na mesma rede consegue comandar. Em Wi-Fi compartilhado, deixe o painel só com quem opera.

## 5. Pessoas

**Fotos:** com a rotina de pé e **desarmada** (**Subir desarmado**), na aba **Pessoas**, digite o nome e escolha até
10 fotos. Para quem já tem foto, escolha **Adicionar às fotos atuais** (padrão) ou **Substituir todas as fotos**
(pede confirmação). A pessoa é reconhecida com as fotos novas na hora. Com várias pessoas na foto, vale o maior rosto:
use fotos com uma pessoa só.

**Pessoa nova:** digite o nome (minúsculas, sem espaço), o **tratamento** e a foto. Ela ganha o gesto
padrão e a fala *"Olá, <tratamento> <Nome>, sou o Tenente Nichinica"*. A rotina vale na **próxima subida**.
Se o nome soar mal, preencha **Nome falado** como ele deve soar.

**Cadastro rápido pela webcam do robô** (recomendado: usa a câmera que vai reconhecer): rotina de pé e **desarmada**;
nome e, para pessoa nova, tratamento; a pessoa **de frente para o robô, a ~1 m, parada por 3 s**; clique
**Fotografar pela webcam do robô** (não o **Salvar**: sem foto escolhida, o Salvar só grava a rotina). Ele usa os 8
quadros dos últimos ~3 s e responde "<nome> cadastrado: N foto(s) aproveitada(s)". Repita de outro ângulo para somar fotos.

**Coronel Aderson:** tem rotina (*"Olá, coronel veterano Aderson, sou o Tenente Nichinica"*) e está no banco
enviado pelo notebook, com 6 fotos. O Gil tem 2. Só esses dois têm rotina no projeto; os cadastrados pelo painel (ex.:
bianco) ficam em `data/reactions.yaml` no robô.

**Remover alguém:** primeiro pare a rotina, depois **Remover** na lista. As fotos são apagadas. Para
gil e aderson, a rotina continua no projeto e pode receber foto nova.

**Sobre usar uma só foto:** com uma foto, a nota varia muito com o ângulo (0,27 a 0,44 de cima contra
0,62 de frente, medido no robô). Use uma foto **de frente, com boa luz e, de preferência, feita na
altura e no lugar em que a webcam vai ver a pessoa**. Se alguém não for reconhecido, acrescente mais
fotos com **Adicionar às fotos atuais**.

Copiar o banco do notebook para o robô apaga quem foi cadastrado pelo painel.

## 6. Trocar webcam ou caixa (só se quiser)

Sem fazer nada, continuam a webcam ligada e a caixa de sempre.

### Webcam

1. **F3+↓** e espere encerrar.
2. Troque a webcam. Deixe **só uma** conectada (a RealSense pode ficar).
3. **Subir desarmado** e confira na aba **Operar** o nome, o formato e o ritmo do reconhecimento.
4. Recalibre a distância de parada (seção 7): outra lente muda o tamanho do rosto.

Para voltar, faça o mesmo com a antiga. Se a nova não der imagem, veja se ela oferece 640×480 em YUYV:
`v4l2-ctl -d /dev/video0 --list-formats-ext`. O painel avisa se a largura real for diferente de `largura_imagem`:
nesse caso, não arme, porque o giro e a distância sairiam errados.

**Intelbras FHD WCI1080P (medido em 2026-11-05, no notebook):** entrega 640×480 em YUYV, mas nesse formato só oferece
30 ou 60 quadros/s. O pedido de 15 no launch vira 30 (aviso `driver overwrote value: 1/30`, inofensivo), e o tráfego
USB dobra para cerca de 18 MB/s. O reconhecimento descarta o excesso, mas acompanhe as **quedas** no painel: se aparecerem,
volte à webcam antiga ou use um hub com fonte própria. Pede até 500 mA. **Não suba a resolução:** em 1280×720 YUYV
ela mediu 13,3 quadros/s, cerca de 24,5 MB/s, perto do limite prático do USB 2.0, que no robô é dividido com Wi-Fi e Bluetooth.

**Vigia da câmera:** desligado desde 2026-11-05. Com a Intelbras, a conexão estável e o reconhecimento ainda aquecendo, ele
derrubava a própria câmera a cada 6 s (`reiniciando o v4l2_camera_node` no log, `0.3/s` no reconhecimento). Para uma webcam que cai
pelo USB, como a antiga, religue-o: `vigia_camera:=true` no `ros2 launch robot_reaction_ros rotina.launch.py`.

**É problema de energia?** Mesma porta, 10 min para cada webcam, comparando:

```bash
journalctl -k --since "-10min" | grep -c "New USB device"
```

Se as duas caírem, a suspeita passa para o hub. Teste com um **hub USB com fonte própria**.

### Caixa de som

1. Ligue a caixa nova em **modo de pareamento**.
2. **Caixa de som → Procurar caixas** (8 s) e **Usar** ao lado dela. Deve soar um bipe. Pode ser feito com a rotina de pé.
3. Se não conectar, **a caixa anterior continua valendo**. Tente de novo.

Para voltar à antiga: **Usar** ao lado da marcada como **(padrão)**. Evite procurar durante uma aproximação: a busca usa o mesmo rádio.

Se o painel não conseguir parear, por SSH (troque o endereço):

```bash
bluetoothctl    # depois: scan on, pair XX:XX:XX:XX:XX:XX, trust XX:XX:XX:XX:XX:XX, connect XX:XX:XX:XX:XX:XX, quit
echo XX:XX:XX:XX:XX:XX > ~/ipe-2-code/data/caixa.txt     # rm desse arquivo volta à padrão
```

## 7. Calibrar e ajustar a aproximação

### Distância de parada (manual)

Refaça ao trocar a webcam ou mudar a altura dela. Na aba **Calibrar**:

1. **Subir desarmado.**
2. Uma pessoa cadastrada fica onde o robô deve parar, de frente para ele. O painel mostra a mediana dos últimos segundos.
3. **Salvar distância.** Grava só esse valor.
4. **PARAR** e suba de novo: vale na próxima subida. Enquanto isso, o topo avisa que há ajustes pendentes.

Maior = para mais perto; menor = mais longe.

### Sentido do giro

Com a pessoa à **direita** da imagem, o desvio fica positivo e o robô deve virar para a direita. Se virar para o outro
lado, pare e marque **Inverter o sentido do giro** em **Velocidade**. Isso só se confere com o robô armado.

### Outros ajustes

Estão recolhidos por grupo na aba **Calibrar**; um grupo com valor fora do padrão abre sozinho e mostra **alterado**. Valem
na próxima subida. O painel recusa valores fora da faixa e combinações que deixariam o robô preso. Além disso, o
`body_worker` nunca envia mais que 0,5 m/s e 0,8 rad/s ao robô, mesmo com outro arquivo de operação.

| Grupo | Ajuste no painel | Campo | Padrão | Faixa | O que faz |
|---|---|---|---|---|---|
| O que o robô faz | Virar, Aproximar, Falar, Gestos, Meia-volta | `estagios` | todos | | Etapas que rodam. Aproximar inclui virar. Meia-volta: gira 180° pela esquerda, passo à frente, depois espera Liberar cumprimentos |
| Distância de parada | Altura do rosto para parar | `altura_caixa_alvo_px` | 90 | 20–400 | Calibração acima |
| Velocidade | Velocidade para frente | `vx` | 0,2 | 0,05–0,5 | m/s, constante. Comece com 0,1 no primeiro teste andando |
| | Giro máximo | `vyaw_max` | 0,3 | 0,1–0,8 | rad/s |
| | Giro mínimo parado | `vyaw_min` | 0,3 | 0–0,8 | rad/s. Abaixo de 0,3 o G1 não girou no lugar |
| | Força da correção do giro | `kp_giro` | 0,6 | 0,1–3 | Giro = força × desvio. Alto demais oscila |
| | Inverter o sentido do giro | `inverter_giro` | não | | Se virar para o lado errado |
| Centralizar a pessoa | Desvio aceito ao só virar | `centro_ok` | 0,15 | 0,02–0,8 | 0 = centro; 1 = borda da imagem |
| | Desvio máximo para andar | `centro_para_andar` | 0,45 | 0,05–1 | Acima disso, para de andar e só gira. Não pode ser menor que `centro_ok` |
| | Desvio aceito ao chegar | `centro_chegada` | 0,30 | 0,02–0,8 | Na distância de parada, aceita isso e cumprimenta. Não pode ser menor que `centro_ok` |
| Perder a pessoa e tempo limite | Parar sem ver o rosto | `perda_rosto_s` | 1 | 0,2–5 | s. Para e espera; retoma se o rosto voltar |
| | Desistir sem ver o rosto | `desistir_s` | 10 | 1–60 | s. Desiste sem cumprimentar. Não pode ser menor que `perda_rosto_s` |
| | Tempo máximo da aproximação | `tempo_max_s` | 30 | 5–120 | s. Desiste mesmo vendo a pessoa |
| Meia-volta | Giro da meia-volta | `vyaw_meia_volta` | 0,5 | 0,3–0,8 | rad/s. Comece com 0,5 |
| | Tolerância do giro | `tolerancia_meia_volta_graus` | 10 | 2–30 | Graus. Para ao chegar a 180° menos isso |
| | Passo à frente | `passo_m` | 0,2 | 0–0,5 | m. 0 = sem passo |
| | Velocidade do passo | `vx_passo` | 0,2 | 0,05–0,3 | m/s |
| | Tempo máximo da meia-volta | `tempo_max_meia_volta_s` | 12 | 5–30 | s. Passou disso, falha |
| Retorno | Velocidade da volta | `vx_retorno` | 0,3 | 0,1–0,5 | m/s |
| | Chegou ao ponto | `tolerancia_retorno_m` | 0,15 | 0,05–0,4 | m do ponto de partida |
| | Distância mínima | `retorno_min_m` | 0,3 | 0–1 | m. Andou menos que isso até a pessoa: não volta |
| | Giro na volta | `vyaw_retorno` | 0,5 | 0,3–0,8 | rad/s. Teto da correção de rumo e do giro final |
| | Ganho do rumo | `kp_rumo` | 1,0 | 0,2–3 | Correção por erro de rumo |
| | Tolerância do giro final | `tolerancia_rumo_graus` | 8 | 2–30 | Graus |
| | Tempo máximo | `tempo_max_retorno_s` | 30 | 5–60 | s, por fase (andar e virar) |
| Voz | Falar "Perdi <nome> de vista" | `avisos_voz` | sim | | Desmarque na apresentação |

### Meia-volta

Depois de um cumprimento com sucesso, o robô gira 180° pela **esquerda**, dá um passo à frente (~0,2 m) e
fica em **"aguardando o operador"** (durante o giro: **"fazendo meia-volta"**). Para continuar: **Liberar
cumprimentos** no painel, ou desligar e ligar o automático (F3+←, duas vezes), ou **cumprimentar agora** (só libera se alguém for reconhecido).
Desarmado, só registra `dry_run meia_volta` (e também espera o operador). **PARAR** ou F3+↓ interrompe o giro
e o passo na hora. O passo é **cego**: deixe ~1 m livre atrás de onde o robô começa. Para não usar, desmarque
**Meia-volta** em **O que o robô faz ao cumprimentar**, na aba **Operar** (vale já no próximo cumprimento; ajustes antigos ganham o estágio na próxima subida; desmarcado, fica
desmarcado). Primeiro uso: meça o giro com `scripts/robo_medir_giro.py`
([`teste-no-robo.md`](teste-no-robo.md), seção 0).

### Retorno ao ponto de partida

Com **Retorno** marcado em **O que o robô faz ao cumprimentar** (desmarcado por padrão), depois da meia-volta o robô
**anda de volta até onde estava quando reconheceu a pessoa** e **vira de frente para ela**, no lugar do passo cego. Não é
preciso marcar distância: ele anota a própria posição (odometria do G1) ao começar e volta até ela, corrigindo o rumo, sem
andar de ré. Status: "retorno: andando (faltam 1.20 m)", "retorno: virando para a pessoa", "retorno: fim". A volta é
**cega**: caminho livre entre a pessoa e o ponto de partida. Para (e registra `retorno: falhou (…)`) se demorar, se estiver
se afastando do ponto ou sem odometria; um retorno que falha ainda conta como cumprimento. **PARAR** ou F3+↓ param na hora.
Se ele não andou até a pessoa (menos de 0,3 m), não volta nem vira. Primeiro uso: `scripts/robo_medir_odometria.py`
([`teste-no-robo.md`](teste-no-robo.md), seção 9a).

**Restaurar padrões** desfaz tudo.

## 8. Como o robô decide

**Se perder o rosto:**

| Sem ver o rosto | O que faz |
|---|---|
| Até 1 s | Continua com a última posição |
| De 1 a 10 s | Para e espera. **Se o rosto voltar, retoma sozinho** |
| 10 s | Desiste, fica em pé e fala **"Perdi <nome> de vista"** |

Ele não gira para procurar a pessoa. Depois de desistir: no manual, aperte **F3+→**; no automático, tenta assim que reconhecer a pessoa de novo.

**No automático:**

- Reconhece a pessoa em **5 quadros**; falhas de até 0,5 s não zeram a contagem.
- Só repete a mesma pessoa se **passaram 5 min e ela saiu da frente por 5 s**. **Liberar cumprimentos** ou **F3+→** ignoram essa espera.
- Pelo menos **10 s** entre dois cumprimentos quaisquer.
- Se o **tempo esgotar**, espera **60 s** antes de tentar a mesma pessoa, para não andar até ela sem parar.
- Se o gesto falhar ou for interrompido, a pessoa conta como cumprimentada: use **Liberar cumprimentos**.

## 9. Se algo der errado

| Sintoma | O que fazer |
|---|---|
| **Andou até a pessoa e não reagiu** | Veja **Eventos**. `desistiu: rosto perdido`: reconhecimento falhou de perto; afaste a parada (`altura_caixa_alvo_px` menor) ou melhore a foto. `desistiu: tempo esgotado`: aumente `tempo_max_s`. `postura … falhou`: envie o log. Depois, **Liberar cumprimentos** |
| **Parou no meio** | Normalmente perdeu o rosto ou a webcam caiu. Veja a contagem de quedas no painel. Ele retoma se voltar a ver a pessoa em até 10 s |
| Chega perto demais | Diminua `altura_caixa_alvo_px`. Com muitas quedas de webcam, resolva-as primeiro: ele anda até 1 s sem imagem |
| "Não estou em equilíbrio, não vou começar." | Ponha em equilíbrio e aperte F3+↑ de novo |
| Braços errados depois de uma parada de emergência no meio de um gesto | Não ande. No suporte: F3+B e F3+A. Sem suporte: reinicie o equilíbrio pelo controle da Unitree antes de subir |
| Combo sem bipe | Caixa desligada? Veja `journalctl --user -u ipe-controle -f` |
| F3+↑ dá dois tons graves | A rotina já está de pé ou subindo: F3+↓ e espere |
| Painel não abre | Rede `IPE-G1`? Use `http://`, não `https://`. Depois, `robo_hotspot.sh estado` e `systemctl --user status ipe-painel` |
| Celular não entra no hotspot | Esqueça a rede no celular e conecte de novo |
| "A webcam reconectou" no painel | A imagem não volta sozinha: **PARAR** (ou F3+↓) e suba de novo. Sem imagem, o robô para em 1 s |
| Automático não cumprimenta | Automático ligado? O nome aparece em **Na frente agora**? A pessoa tem foto e rotina em **Pessoas**? Depois, **Liberar cumprimentos** |
| `meia_volta: falhou (...)` | `tempo esgotado`: aumente `tempo_max_meia_volta_s` ou confira o piso. `sem angulo`: o IMU não chegou. `interrompida`: PARAR. `girou para o lado errado`: ele parou sozinho; **avise o autor** e não arme de novo. Depois, Liberar cumprimentos |
| Ficou parado "aguardando o operador" | É o esperado depois da meia-volta: **Liberar cumprimentos** (ou automático desligado e ligado, ou cumprimentar agora) |
| Aparece `desconhecido` | Mais luz, pessoa mais perto, foto melhor (seção 5) |
| F3+Y: "Não entendi" sempre | Esperado enquanto o reconhecimento de fala não estiver instalado. Teste por texto; meça o microfone com `robo_medir_voz.sh` |
| Aviso "Microfone da webcam não encontrado" | `arecord -l`; escreva o dispositivo certo em `data/microfone.txt` e suba de novo |
| Cumprimento recusado, sem fala | Posição mantida por voz: **À vontade** (F3+X) |
| Sem som | **Testar som**. Veja se a caixa está conectada e é a saída padrão no painel |

**Logs para enviar:**

```bash
grep -rE "desistiu|falhou|ERRO" ~/.ros/log/latest/ | tail -30
journalctl --user -u ipe-controle --since "-10min"
journalctl --user -u ipe-painel --since "-10min"
tmux attach -t rotina     # janelas "rotina" e "status"; Ctrl+b d sai sem parar
```

## 10. Conferência rápida antes de usar

Pare no primeiro item que falhar.

**Sem mexer o robô**

- [ ] Celular na `IPE-G1`, painel abre, faixa do topo sem alerta.
- [ ] **Testar som** dá bipe.
- [ ] **Subir desarmado**: em ~1 min, seu rosto aparece em **Na frente agora**.
- [ ] Foto nova cadastrada e o nome da pessoa aparece.
- [ ] **PARAR**: volta a "rotina parada".

**No suporte**

- [ ] **F3+A** levanta. Um toque rápido em **F3+B** não faz nada.

**Fora do suporte, com espaço**

- [ ] **F3+↑**, depois **F3+→** com a pessoa de lado: vira para o lado certo.
- [ ] Pessoa a ~3 m: anda, para na distância certa e faz o gesto com a fala.
- [ ] **F3+↓ andando**: para na hora.
- [ ] Pessoa sai da frente andando: para; fala "Perdi <nome> de vista" em ~10 s.
- [ ] **F3+↓ e F3+↑** em seguida: sobe de novo.
- [ ] **F3+←**: cumprimenta sozinho uma vez e não repete com a pessoa parada.
- [ ] **Voz**: `arecord` presente; F3+Y, falar "sentido" e soltar: o painel passa por "gravando" e fica "segurando sentido"; F3+X solta.
- [ ] **Continência** segurada: F3+X e depois F3+↓. Observe a folga dos braços (soltar pula o desc. arma).

## 11. Melhorar a precisão

Em ordem de custo. **Só os itens 1 a 3 são para já:** não exigem mudar código.

| # | O que fazer | Por quê |
|---|---|---|
| 1 | **Foto feita na posição da webcam**, com boa luz | A maior variação medida foi de ângulo: 0,27 a 0,44 de cima contra 0,62 de frente |
| 2 | **2 ou 3 fotos para quem falhar** | O banco usa o centroide das fotos, então mais fotos não aumentam o falso positivo como o máximo aumentaria |
| 3 | **Webcam à altura e inclinada para o rosto; luz de frente** | Rosto de perfil, de cima ou em contraluz perde nota |
| 4 | **Calibrar o limiar** com `python -m scripts.calibrar_limiar` | 0,35 foi escolhido em campo. A referência do InsightFace é 0,30–0,45. Exige pelo menos 3 fotos por pessoa e alguém não cadastrado; com uma foto só não dá |
| 5 | **Margem entre o 1º e o 2º mais parecidos** | Proposta na revisão de 18/09 e ainda não implementada. Com limiar baixo, evita confundir duas pessoas parecidas |
| 6 | **Seguir a caixa do rosto entre quadros** | Mantém a identidade quando o nome oscila. É o que mais reduziria "perdi de vista" |
| 7 | **Distância pela profundidade da D435i** em vez de pixels | Proposta da Fase 2: parar por metros (faixa de 0,3–3 m), independentemente da câmera e do rosto |
| 8 | **Mais resolução** (ex.: 1280×720) | Simulando com as fotos do banco, só ajuda com o rosto abaixo de ~40 px; de 50 px para cima a nota quase não muda. Satura o USB 2.0 com YUYV (seção 6): só com outro barramento ou formato |

**Não vale trocar de modelo agora:** o `buffalo_l` já é o padrão e o reconhecedor do `antelopev2` não
mostra ganho na tabela do InsightFace (MR-ALL 91,25 contra 90,66 do R100@Glint360K).
Os pacotes `buffalo_s`/`buffalo_sc` são bem piores (71,87).

Referências: `IPE2_propostas_2026-09-18` no Dropbox (`ANALISE/00_QUADRO_VEREDITO`, `ANALISE/02`, `PROPOSTAS/FASE2`) e `UNITREE_G1_base_documentacao/MD/insightface_model_zoo_README.md`.

Testes passo a passo de cada função: [`teste-no-robo.md`](teste-no-robo.md).
