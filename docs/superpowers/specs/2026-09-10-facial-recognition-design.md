# Reconhecimento facial de pessoas a partir de fotos — Design

Data: 2026-09-10
Contexto: Projeto IME, robô humanoide Unitree G1. Fase atual: protótipo local
com webcam, em Python, rodando em Linux (WSL2). Fase futura (fora de escopo
deste documento): portar para a Jetson Orin NX do robô e integrar com ROS2,
acionando movimentação/continência ao reconhecer a pessoa.

## Objetivo

A partir de um pequeno conjunto de fotos de referência por pessoa (poucas
fotos, possivelmente de fontes públicas/online, qualidade e ângulos
variados), reconhecer essas pessoas em vídeo ao vivo de uma webcam comum,
exibindo o nome e a confiança sobre o rosto detectado.

## Não-objetivos (fora de escopo agora)

- Integração com ROS2 ou com o robô físico.
- Movimentação do robô / lógica de interação (continência, aproximação).
- Banco de dados de identidades em larga escala (dezenas/centenas de
  pessoas) — o volume esperado é pequeno (poucas identidades).
- Autenticação/controle de acesso de segurança crítica.

## Abordagem técnica

Usar **InsightFace** (detector RetinaFace + embeddings ArcFace, modelo
`buffalo_l`), via ONNX Runtime:

- Melhor acurácia de reconhecimento com poucas fotos de referência de
  qualidade variável, comparado a alternativas como MediaPipe+dlib
  (`face_recognition`) ou YOLO-face (que resolve só detecção, não
  identidade).
- Modelos em formato ONNX portam diretamente para a Jetson Orin NX via
  `onnxruntime-gpu`/TensorRT, sem mudar a lógica de aplicação.

## Arquitetura e componentes

```
[fotos de referência] --> enroll.py --> [banco de embeddings local]
                                              ^
                                              |
[webcam] --> webcam_demo.py (usa core/) --> compara --> overlay na tela
```

- **`core/face_engine.py`** — wrapper fino sobre
  `insightface.app.FaceAnalysis`. Função pura
  `extract_faces(frame) -> list[FaceResult]` (bbox + embedding + score).
  Não conhece webcam nem nomes de pessoas.
- **`core/identity_store.py`** — persistência e consulta de embeddings
  conhecidos. Funções: `enroll(name, embeddings)`,
  `match(embedding) -> (name | None, confidence)`, `load()/save()`.
- **`apps/enroll.py`** (CLI) — lê `data/known_faces/<nome>/*.jpg`, roda o
  `face_engine` em cada imagem, e cadastra os embeddings via
  `identity_store.enroll`.
- **`apps/webcam_demo.py`** (CLI) — captura da webcam via
  `cv2.VideoCapture`, laço: frame → `face_engine.extract_faces` →
  `identity_store.match` por rosto → desenha bbox+nome+confiança →
  `cv2.imshow`.

`core/` é totalmente desacoplado de webcam/CLI — na portagem futura para o
robô, troca-se apenas a fonte do frame e o destino do resultado.

## Dados e armazenamento

```
data/known_faces/
  <nome_pessoa>/
    foto1.jpg
    foto2.jpg
data/identity_db.npz    # {name: [emb1, emb2, ...]}
data/identity_db.json   # metadados (qtd de fotos, data de cadastro)
```

- Guardamos **todos** os embeddings de cada foto cadastrada por pessoa
  (não uma média), pois com poucas fotos variadas isso é mais robusto do
  que colapsar num único vetor médio.
- **Matching:** para cada rosto detectado, calcular similaridade de
  cosseno contra todos os embeddings cadastrados de todas as pessoas;
  se a maior similaridade > limiar configurável (padrão inicial: 0.45),
  rotula com esse nome e a confiança; caso contrário, "Desconhecido".
- **Config centralizada** (`core/config.py`): índice da câmera, limiar de
  similaridade, tamanho de detecção do modelo.

## Tratamento de erros

- Nenhum rosto no frame → segue o loop sem overlay.
- Câmera não encontrada/índice inválido → erro claro, encerra (falha
  rápida).
- Foto de enrollment sem rosto detectável → avisa no console qual
  arquivo falhou e pula, sem abortar o cadastro das demais.
- Múltiplos rostos no frame → cada um processado e rotulado
  independentemente.

## Plano de testes

- **Unitários (pytest):**
  - `identity_store`: similaridade de cosseno, aplicação do limiar,
    persistência (save/load) — com vetores sintéticos, sem depender do
    modelo pesado.
  - `face_engine`: usando a imagem de amostra já embutida no próprio
    pacote `insightface` (`insightface.data.get_image("t1")`), sem
    precisar versionar fotos de pessoas reais no repositório —
    verificando detecção de rosto e dimensão do embedding retornado.
- **Validação com vídeo gravado:** gravar um pequeno vídeo de teste
  (webcam) com pessoas cadastradas e não cadastradas, para servir como
  teste de regressão repetível ao longo do desenvolvimento.
- **Validação manual ao vivo:** quem estiver montando o projeto tira
  fotos próprias, cadastra via `enroll.py` e testa reconhecimento ao
  vivo via `webcam_demo.py`, avaliando falsos positivos/negativos.
  Feito de forma guiada durante a implementação, não automatizável.

## Ambiente e riscos de setup

- Python do sistema é 3.14. **Verificado em 2026-09-11:** `numpy==2.5.3`,
  `opencv-python==5.0.0.93`, `onnxruntime==1.30.0` e `insightface==2.0`
  têm wheels para 3.14 e instalam/importam sem conflito; o download e
  preparo do modelo `buffalo_l` (~280MB, primeira execução, requer
  internet) e a detecção em uma imagem real foram testados com sucesso.
  Não é necessário um Python separado — usamos um virtualenv comum
  (`python3 -m venv`) com o Python do sistema.
- WSL2 não acessa webcam USB nativamente. Mitigação: configurar
  `usbipd-win` para passthrough USB do Windows ao WSL; se isso for
  custoso, usar vídeo gravado como alternativa durante o
  desenvolvimento.
- Alvo de portagem futura: Jetson Orin NX (JetPack 6) no Unitree G1,
  usando `onnxruntime-gpu`/TensorRT — fora do escopo de implementação
  agora, mas a escolha de InsightFace/ONNX já é feita pensando nisso.
