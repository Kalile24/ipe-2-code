# Painel web de monitoramento e operação — Design

Data: 2026-11-04. Implementado no mesmo dia (verificado no Docker Foxy; **ainda não no robô**: ver
[`teste-no-robo.md`](../../guides/teste-no-robo.md), passo 8). Contexto: passo 3 depois da rotina
(`2026-10-29-…`) e da aproximação (`2026-11-04-aproximacao-e-estagios-design.md`).

**Revisão de 2026-11-05 (pedido do usuário, painel como local de acompanhamento sem cabo):** abas Operar, Calibrar, Pessoas
e Sistema; `armado` vem do anúncio do `body_node` e do parâmetro `armed`, não mais do histórico; aviso de conexão perdida;
faixas de segurança ao salvar (`core.approach.validar_operacao`) e teto no `body_worker`; POST de outra origem recusado;
`Cadastrar.srv` ganhou `adicionar`; até 10 fotos; falha de subida visível; eventos agrupados; diagnóstico em texto; calibração
guiada da distância de parada. Com isso, o que está abaixo sobre a "proteção" e o formulário vale só como histórico. Guia:
`docs/guides/operar-o-robo.md`.

## Decisões do usuário (2026-11-04)

- Uma interface para ver as funções críticas: em que estágio o robô está, quem está sendo
  reconhecido, se a câmera está conectada; e para cadastrar alguém por foto.
- **Cadastro por foto no robô, só daquela pessoa**: o face_recognition_node (que já tem o modelo
  carregado) calcula os embeddings e (re)cadastra só ela no banco; as outras não mudam e as fotos
  não ficam no robô. A regra antiga ("cadastre no notebook") continua valendo para cadastros em
  lote; **copiar o banco do notebook para o robô apaga quem foi cadastrado pelo painel**.
- **O robô cria a própria rede Wi-Fi** (hotspot no `wlan0`), sabendo que isso tira o robô da rede
  em que estava e para a transmissão da D435i do `~/cesar` enquanto estiver ligado.

## Como ficou (decisões minhas)

- `painel_node` (ROS, só biblioteca padrão + rclpy + yaml), porta 8080, uma página
  (`painel/index.html`) que se atualiza a cada 1 s. Serviço de usuário próprio
  (`scripts/systemd/ipe-painel.service`), de pé mesmo com a rotina parada. Sem login: a proteção é
  a senha do hotspot.
- Mostra: câmera (tem publicador no tópico de imagem — o painel não assina as imagens, pesariam no
  Jetson), reconhecimento (ritmo das detecções), quem está na frente com nota e **altura da caixa em
  px** (para escolher `altura_caixa_alvo_px`), estágio do robô (pela última linha do
  `/reaction/rotina_status`), armado, reações automáticas, últimos 15 eventos e quem tem rotina.
- Comandos: subir desarmado, subir armado (= `--controle`: só em equilíbrio, automático desligado),
  cumprimentar agora, liga/desliga automático, parar (Ctrl+C na janela `rotina`).
- Operação: formulário dos campos do `operacao.yaml` que fazem sentido ajustar; salva em
  `data/operacao.yaml` (fora do git), que o `robo_rotina_cumprimento.sh` passa a usar por padrão.
- Cadastro: nome (minúsculas, números e `_`, igual à chave do `reactions.yaml`) e 1–5 fotos; o
  navegador reduz cada foto a ≤ 1280 px antes de mandar. Serviço `~/cadastrar`
  (`robot_reaction_interfaces/srv/Cadastrar`) no face_recognition_node, na mesma thread das imagens.
  Cadastrado sem rotina no `reactions.yaml` só é reconhecido, não cumprimentado (o painel avisa).
- Hotspot: `scripts/robo_hotspot.sh liga|desliga|estado` (rede `IPE-G1`; `desliga` volta para a
  conexão Wi-Fi anterior). Painel no hotspot: `http://10.42.0.1:8080`.
