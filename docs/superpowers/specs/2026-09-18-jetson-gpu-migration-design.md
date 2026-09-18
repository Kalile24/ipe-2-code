# Portagem do nó ROS2 pro Jetson Orin NX (Unitree G1 EDU) — Design

Data: 2026-09-18
Contexto: o nó ROS2 `face_recognition_ros` (spec anterior:
`2026-09-12-ros2-node-migration-design.md`) já está validado localmente —
build, testes e reconhecimento real confirmados via Docker + webcam +
`v4l2_camera`, rodando 100% em CPU. Este documento cobre o próximo passo:
preparar esse mesmo pacote pra rodar de verdade no computador de bordo do
robô (Jetson Orin NX), usando a câmera real (Intel RealSense D435i) e a GPU
da Jetson pra acelerar a inferência.

**Sem acesso físico ao robô ou a uma Jetson avulsa no momento da escrita.**
Este é um documento de planejamento: cobre o código que já dá pra escrever
e testar (a parte "cola", sem GPU real disponível) e um guia de instalação
com os passos e riscos a verificar no primeiro acesso ao hardware.

## Risco #1 (bloqueante, verificar no dia 1): versão real de Ubuntu/ROS2/JetPack

O spec anterior assumiu Ubuntu 22.04 + ROS2 Humble com base na documentação
do SDK `unitree_ros2`. Uma thread de fórum (fonte não-oficial, usuário
comum, não confirmada pela Unitree) afirma que o G1 atualmente roda
**ROS2 Foxy em Ubuntu 20.04 + JetPack 5** no computador de bordo — o
`unitree_ros2` provavelmente documenta o requisito do **PC externo de
desenvolvimento**, que é uma máquina diferente do computador de bordo do
robô (PC2/Jetson).

**Decisão (aprovada com o usuário):** desenhar este documento e o plano de
implementação assumindo **Humble** (mantém consistência com tudo que já foi
construído — pacote, testes, specs, guias), e tratar a confirmação da
versão real como a **primeira tarefa, bloqueante**, do plano de
implementação. Se o computador de bordo vier com Foxy/Ubuntu 20.04, as
diferenças conhecidas de API a re-verificar são as mesmas classes de
problema já encontradas nesta migração (formato de mensagens `vision_msgs`,
que teve uma mudança real de shape entre versões; comportamento de
`rclpy`). Nenhuma linha de código deste design deve ser tratada como
correta até essa verificação acontecer.

## Objetivo

Ter o `face_recognition_ros` pronto pra rodar no Jetson Orin NX do G1 EDU:
assinando a câmera real (`realsense2_camera`) em vez da webcam local, e
usando a GPU da Jetson (via ONNX Runtime + TensorRT/CUDA) em vez de CPU,
sem exigir reescrever a arquitetura já validada.

## Não-objetivos (fora de escopo agora)

- Reexportar os modelos do InsightFace como engines TensorRT nativos
  (`.engine`/`.plan`) — ganho de performance adicional sobre a Etapa 1,
  mas exige build específico por dispositivo e troca da camada de
  inferência do `FaceEngine`. Documentado na seção **Otimizações futuras**
  como próximo passo, não implementado agora.
- Pipeline `DeepStream` da NVIDIA — overkill pro escopo de um nó de
  reconhecimento facial que já funciona bem com ROS2 puro. Citado só por
  completude na seção **Otimizações futuras**.
- Lógica de navegação/interação/movimento do robô (mesmo não-objetivo do
  spec anterior — continua sendo trabalho de uma fase futura).
- Instalar ROS2/`unitree_ros2` do zero no computador de bordo — assume-se
  que o robô já vem com esse SDK configurado de fábrica; o guia cobre
  *adicionar* nosso pacote a esse ambiente, não recriá-lo.

## Arquitetura

Duas mudanças pontuais sobre o pacote já existente, sem reestruturação:

1. **`FaceEngine` aceita uma lista de execution providers do ONNX
   Runtime**, em vez de assumir CPU implicitamente. Confirmado na fonte
   (`insightface/app/face_analysis.py`, branch `master`): `FaceAnalysis`
   já aceita `providers` via `**kwargs` e repassa pro `onnxruntime`
   internamente — não precisa trocar de biblioteca nem reescrever o
   `FaceEngine`.
2. **`launch/face_recognition.launch.py` ganha um argumento `camera`**
   (`v4l2` default — preserva o caminho de teste local já validado;
   `realsense` — sobe `realsense2_camera` em vez de `v4l2_camera` pro robô
   real). Só troca qual nó de câmera é lançado; `face_recognition_node` não
   muda.

Nenhum call site existente (protótipo standalone, Docker local) muda de
comportamento — CPU continua sendo o padrão em tudo que já roda hoje. GPU e
câmera real são **overrides explícitos**, só usados no lançamento de
produção no robô — mesmo princípio já usado com `model_name` (feature
recém-mesclada na `master`).

## Componentes

### `core/config.py`

Nova constante, mesmo padrão de `MODEL_NAME`:

```python
ONNX_PROVIDERS = ["CPUExecutionProvider"]
```

### `core/face_engine.py`

```python
class FaceEngine:
    def __init__(
        self,
        det_size: tuple[int, int] = (640, 640),
        model_name: str = "buffalo_l",
        providers: list[str] | None = None,
    ):
        self._app = FaceAnalysis(
            name=model_name,
            allowed_modules=["detection", "recognition"],
            providers=providers or ["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=0, det_size=det_size)
```

### `face_recognition_node.py`

Novo parâmetro ROS2 `onnx_providers` (lista de strings), mesmo padrão de
`model_name`:

```python
self.declare_parameter("onnx_providers", ONNX_PROVIDERS)
...
providers = self.get_parameter("onnx_providers").value
self._engine = FaceEngine(det_size=DET_SIZE, model_name=model_name, providers=providers)
```

No robô, o launch/parâmetro passa
`["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]`.
Em qualquer outro ambiente (Docker local, protótipo), o parâmetro é
simplesmente omitido e o default (`["CPUExecutionProvider"]`) preserva o
comportamento já validado.

### `launch/face_recognition.launch.py`

Argumento `camera` (`v4l2` | `realsense`) seleciona qual `Node` de câmera
entra na `LaunchDescription` — usando `IfCondition`/`UnlessCondition` do
pacote `launch.conditions` (padrão comum do ROS2 pra isso, sem precisar de
lógica Python custom). O `face_recognition_node` continua ouvindo o mesmo
nome de tópico (`/camera/color/image_raw` por default); com `camera:=realsense`,
o `realsense2_camera` publica nesse tópico (ou é remapeado pra ele, igual
já fazemos com o `v4l2_camera` hoje).

**Risco a verificar no dia 1 (não bloqueante pro código, mas pro teste
real):** o nome exato do tópico de imagem do `realsense2_camera` varia
entre versões do pacote `realsense-ros` — a maioria publica em
`/camera/color/image_raw`, mas versões mais novas usam
`/camera/camera/color/image_raw` (namespace duplicado). O parâmetro
`image_topic` que o `face_recognition_node` já expõe (desde o spec
anterior) cobre esse caso — só ajustar o valor, sem mudar código.

## Tratamento de erros

- **Provider indisponível:** o ONNX Runtime já tem fallback nativo — se
  `TensorrtExecutionProvider` não estiver disponível na instalação
  (ex: `onnxruntime` não foi compilado com suporte a TensorRT), ele é
  ignorado silenciosamente e o próximo da lista é usado, até chegar em
  `CPUExecutionProvider` (sempre disponível). Isso significa que a lista de
  providers da Jetson pode ser passada com segurança mesmo antes de
  confirmar exatamente quais estão ativos — mas **isso precisa ser
  confirmado empiricamente no hardware real** (`ort.get_available_providers()`)
  antes de assumir que a aceleração está de fato acontecendo, não só
  caindo silenciosamente pra CPU.
- Demais tratamentos de erro (falha do `cv_bridge`, banco de identidades
  vazio, zero rostos) — inalterados do spec anterior.

## Plano de testes

- Testes automatizados cobrem só a "cola": `FaceEngine` aceita e repassa
  `providers` corretamente pro `FaceAnalysis` (mesmo nível de teste já
  feito pra `model_name` — não testa se a GPU acelera de verdade, só que o
  parâmetro chega no lugar certo).
- Validação real de aceleração por GPU/TensorRT **não pode ser
  automatizada sem o hardware** — vira um checklist manual, documentado no
  guia de instalação, pro primeiro dia de acesso à Jetson.

## Guia de instalação (`docs/guides/jetson-deployment.md`)

Novo documento, mesmo espírito do `docs/guides/ros2-docker.md` (passo a
passo + troubleshooting), cobrindo:

1. **Passo 0, bloqueante:** confirmar a versão real de Ubuntu (`lsb_release -a`),
   ROS2 (`ros2 --version` ou `printenv ROS_DISTRO`) e JetPack
   (`dpkg -l | grep nvidia-jetpack` ou `cat /etc/nv_tegra_release`) no
   computador de bordo, antes de qualquer instalação.
2. Instalar `onnxruntime-gpu` com suporte a TensorRT: a Jetson é ARM64 e
   usa builds próprias da NVIDIA — **não é o `pip install onnxruntime-gpu`
   genérico do PyPI** (esse é x86_64). Referências reais:
   - [onnxruntime.ai — TensorRT Execution Provider (docs oficiais)](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html)
   - [Fórum NVIDIA — instalação de onnxruntime em Jetson AGX Orin](https://forums.developer.nvidia.com/t/onnxruntime-installation-on-jetson-agx-orin-developer-kit/368180)
   - [guyin24/onnxruntime-gpu-for-jetson — wheels pré-compiladas pra JetPack 6.1/6.2.x](https://github.com/guyin24/onnxruntime-gpu-for-jetson)
   - Se nenhuma wheel pré-compilada bater com o JetPack real detectado no
     Passo 0, compilar do fonte é o último recurso (mais lento, mas
     sempre funciona).
3. Verificar que os providers de GPU realmente carregaram:
   `python3 -c "import onnxruntime as ort; print(ort.get_available_providers())"`
   deve listar `TensorrtExecutionProvider`/`CUDAExecutionProvider`, não só
   `CPUExecutionProvider`.
4. Trocar a câmera do launch: `ros2 launch face_recognition_ros
   face_recognition.launch.py camera:=realsense`. Se não houver detecção,
   primeiro confirmar o tópico real publicado (`ros2 topic list`) antes de
   assumir bug — ver risco de nome de tópico acima.
5. Deploy nativo (sem Docker) direto no computador de bordo — GPU
   passthrough em Docker na Jetson exige configuração extra
   (`nvidia-container-runtime`) que não compensa pra um robô já com o
   ambiente ROS2 nativo disponível.
6. Seção **Otimizações futuras**, documentando sem implementar:
   - **Etapa 2 — engines TensorRT nativos:** reexportar os modelos ONNX do
     InsightFace pra `.engine`/`.plan` via `trtexec` ou API Python do
     TensorRT, direto na Jetson (engine não é portável entre
     hardware/versões — tem que ser gerado no dispositivo final). Ganho
     adicional sobre o TensorRT Execution Provider do ONNX Runtime, ao
     custo de uma etapa de build por modelo e troca da camada de
     inferência do `FaceEngine`. Só vale a pena se a Etapa 1 não for
     rápida o suficiente na prática.
   - **Etapa 3 — DeepStream:** pipeline dedicado da NVIDIA pra
     câmera→GPU, citado por completude — adiciona uma stack inteira nova
     (GStreamer + plugins DeepStream) que não se justifica pro escopo
     atual de um único nó de percepção.

## Dependências novas

- `onnxruntime-gpu` (build ARM64/JetPack-específico, não PyPI genérico) —
  substitui o `onnxruntime` (CPU) só no ambiente da Jetson; o `.venv`/
  container local de desenvolvimento continuam usando o `onnxruntime` de
  CPU normalmente.
- `realsense2_camera` (pacote ROS2 padrão, já usado como referência desde
  o spec anterior).

## Riscos abertos (resumo)

1. **Versão real de Ubuntu/ROS2/JetPack no computador de bordo**
   (bloqueante — ver seção dedicada acima).
2. **Nome exato do tópico de imagem do `realsense2_camera`** — varia entre
   versões do `realsense-ros`; o parâmetro `image_topic` já existente
   cobre o ajuste, só precisa do valor certo no dia 1.
3. **Wheel de `onnxruntime-gpu` compatível com o JetPack real** — pode não
   existir pré-compilada pro JetPack exato do robô; compilar do fonte é o
   fallback garantido, mas mais lento.
4. **Ganho real de performance não medido** — todo o design assume que o
   TensorRT/CUDA Execution Provider entrega latência bem menor que os
   ~900ms (CPU, `buffalo_l`) já medidos localmente, mas isso só se
   confirma com hardware real. Etapas 2/3 ficam disponíveis caso a Etapa 1
   não seja suficiente.
