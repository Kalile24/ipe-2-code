# Facial Recognition Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python prototype that enrolls known people from a few
reference photos and recognizes them live from a webcam feed (or a recorded
video file), before any Jetson/robot integration.

**Architecture:** Two pure, decoupled `core/` modules — `face_engine.py`
(detection + embedding via InsightFace) and `identity_store.py`
(persistence + cosine-similarity matching) — driven by two thin `apps/`
CLI scripts (`enroll.py`, `webcam_demo.py`). `core/` never imports `cv2`
video capture or argparse, so porting to the robot later only swaps the
frame source/sink.

**Tech Stack:** Python 3.14 (system default — verified compatible, see
below), InsightFace 2.0 (RetinaFace detector + ArcFace embeddings,
`buffalo_l` model) via ONNX Runtime, OpenCV for image/video I/O, pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-facial-recognition-design.md`

## Global Constraints

- Model: InsightFace `buffalo_l`, `allowed_modules=["detection", "recognition"]`,
  `det_size=(640, 640)`, `ctx_id=0`.
- Embeddings: ArcFace 512-d `float32` vectors, L2-normalized
  (`face.normed_embedding`).
- Matching: cosine similarity against **every** stored embedding (not an
  averaged one), default threshold `0.45`, configurable.
- Pinned dependencies (verified installable and importable together on
  this machine's system Python 3.14 on 2026-09-11 — see Task 1):
  `numpy==2.5.3`, `opencv-python==5.0.0.93`, `onnxruntime==1.30.0`,
  `insightface==2.0`, `pytest==9.1.1`.
- `core/` modules must not import `cv2.VideoCapture`, `argparse`, or
  anything webcam/CLI-specific — that lives only in `apps/`.
- Real people's photos and generated embedding databases
  (`data/known_faces/*`, `data/identity_db.*`) are never committed to git.

---

## Task 1: Project scaffolding and environment

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `core/__init__.py`
- Create: `core/config.py`
- Create: `apps/__init__.py`
- Create: `tests/__init__.py`
- Create: `data/known_faces/.gitkeep`

**Interfaces:**
- Produces: `core/config.py` module-level constants used by every later
  task — `CAMERA_INDEX: int`, `SIMILARITY_THRESHOLD: float`,
  `DET_SIZE: tuple[int, int]`, `KNOWN_FACES_DIR: str`, `DB_PATH: str`.
  A `.venv/` virtualenv with all pinned dependencies installed.

- [ ] **Step 1: Write `requirements.txt`**

```
numpy==2.5.3
opencv-python==5.0.0.93
onnxruntime==1.30.0
insightface==2.0
pytest==9.1.1
```

- [ ] **Step 2: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/known_faces/*
!data/known_faces/.gitkeep
data/identity_db.npz
data/identity_db.json
```

- [ ] **Step 3: Create empty package marker files**

Create `core/__init__.py`, `apps/__init__.py`, and `tests/__init__.py`,
each empty (0 bytes).

- [ ] **Step 4: Write `core/config.py`**

```python
CAMERA_INDEX = 0
SIMILARITY_THRESHOLD = 0.45
DET_SIZE = (640, 640)
KNOWN_FACES_DIR = "data/known_faces"
DB_PATH = "data/identity_db"
```

- [ ] **Step 5: Create the known-faces placeholder**

Create `data/known_faces/.gitkeep` (empty file), so the folder exists in
git even though its real photo contents are gitignored.

- [ ] **Step 6: Create the virtualenv**

Run: `python3 -m venv .venv`

This uses the system Python 3.14 directly — no separate interpreter
needed. All pinned dependencies above have confirmed wheels for 3.14.

- [ ] **Step 7: Install dependencies**

Run: `.venv/bin/pip install -r requirements.txt`

Expected: completes with no errors (may take a few minutes; `insightface`
pulls in `scipy`/`scikit-image`/`onnx` as transitive dependencies).

- [ ] **Step 8: Verify the install**

Run:
```bash
.venv/bin/python -c "import cv2, numpy, onnxruntime, insightface; print('ok')"
```
Expected output: `ok`

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore core/__init__.py core/config.py apps/__init__.py tests/__init__.py data/known_faces/.gitkeep
git commit -m "Add project scaffolding, config, and pinned dependencies"
```

---

## Task 2: `core/identity_store.py` — embedding persistence and matching

**Files:**
- Create: `core/identity_store.py`
- Test: `tests/test_identity_store.py`

**Interfaces:**
- Consumes: `numpy` only — no dependency on Task 1's `config.py` values
  (threshold and db path are passed in by the caller).
- Produces:
  - `cosine_similarity(a: np.ndarray, b: np.ndarray) -> float`
  - `class IdentityStore`:
    - `__init__(self, db_path: str)`
    - `.embeddings: dict[str, list[np.ndarray]]`
    - `.enroll(self, name: str, embeddings: list[np.ndarray]) -> None`
    - `.match(self, embedding: np.ndarray, threshold: float) -> tuple[str | None, float]`
    - `.save(self) -> None` — writes `<db_path>.npz` + `<db_path>.json`
    - `.load(self) -> None` — populates `.embeddings`; no-op if the
      `.npz` file doesn't exist yet

- [ ] **Step 1: Write the failing tests**

Create `tests/test_identity_store.py`:

```python
import numpy as np
import pytest

from core.identity_store import IdentityStore, cosine_similarity


def test_cosine_similarity_identical_vectors():
    a = np.array([1.0, 0.0, 0.0])
    assert cosine_similarity(a, a) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_match_above_threshold_returns_name():
    store = IdentityStore(db_path="unused")
    store.enroll("alice", [np.array([1.0, 0.0, 0.0])])
    query = np.array([0.9, 0.1, 0.0])

    name, score = store.match(query, threshold=0.5)

    assert name == "alice"
    assert score > 0.5


def test_match_below_threshold_returns_none():
    store = IdentityStore(db_path="unused")
    store.enroll("alice", [np.array([1.0, 0.0, 0.0])])
    query = np.array([0.0, 1.0, 0.0])

    name, score = store.match(query, threshold=0.5)

    assert name is None


def test_load_with_no_existing_file_is_empty(tmp_path):
    store = IdentityStore(db_path=str(tmp_path / "missing"))
    store.load()
    assert store.embeddings == {}


def test_save_and_load_round_trip(tmp_path):
    db_path = str(tmp_path / "db")
    store = IdentityStore(db_path)
    store.enroll("alice", [np.array([1.0, 0.0, 0.0], dtype=np.float32)])
    store.enroll("bob", [np.array([0.0, 1.0, 0.0], dtype=np.float32)])
    store.save()

    loaded = IdentityStore(db_path)
    loaded.load()

    assert set(loaded.embeddings.keys()) == {"alice", "bob"}
    np.testing.assert_allclose(loaded.embeddings["alice"][0], [1.0, 0.0, 0.0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_identity_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.identity_store'`

- [ ] **Step 3: Implement `core/identity_store.py`**

```python
import json
from pathlib import Path

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class IdentityStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.embeddings: dict[str, list[np.ndarray]] = {}

    def enroll(self, name: str, embeddings: list[np.ndarray]) -> None:
        self.embeddings.setdefault(name, []).extend(embeddings)

    def match(self, embedding: np.ndarray, threshold: float) -> tuple[str | None, float]:
        best_name = None
        best_score = 0.0
        for name, known_embeddings in self.embeddings.items():
            for known in known_embeddings:
                score = cosine_similarity(embedding, known)
                if score > best_score:
                    best_name, best_score = name, score
        if best_score >= threshold:
            return best_name, best_score
        return None, best_score

    def save(self) -> None:
        names = []
        arrays = []
        counts = {}
        for name, embs in self.embeddings.items():
            counts[name] = len(embs)
            for emb in embs:
                names.append(name)
                arrays.append(emb)

        npz_path = self.db_path.with_suffix(".npz")
        json_path = self.db_path.with_suffix(".json")
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        if arrays:
            np.savez(npz_path, names=np.array(names), embeddings=np.stack(arrays))
        else:
            np.savez(npz_path, names=np.array([]), embeddings=np.array([]))
        json_path.write_text(json.dumps({"counts": counts}, indent=2))

    def load(self) -> None:
        npz_path = self.db_path.with_suffix(".npz")
        self.embeddings = {}
        if not npz_path.exists():
            return
        data = np.load(npz_path)
        for name, embedding in zip(data["names"], data["embeddings"]):
            self.embeddings.setdefault(str(name), []).append(embedding)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_identity_store.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add core/identity_store.py tests/test_identity_store.py
git commit -m "Add IdentityStore for embedding persistence and cosine matching"
```

---

## Task 3: `core/face_engine.py` — detection and embedding extraction

**Files:**
- Create: `core/face_engine.py`
- Test: `tests/test_face_engine.py`

**Interfaces:**
- Consumes: `insightface.app.FaceAnalysis`, `core.config.DET_SIZE`
  (only as the caller's default argument — `face_engine.py` itself
  doesn't import `core.config`, keeping it independently testable).
- Produces:
  - `@dataclass class FaceResult`: `bbox: tuple[int, int, int, int]`,
    `embedding: np.ndarray` (shape `(512,)`, `float32`), `det_score: float`
  - `class FaceEngine`:
    - `__init__(self, det_size: tuple[int, int] = (640, 640))`
    - `.extract_faces(self, frame: np.ndarray) -> list[FaceResult]`

**Note:** the first time `FaceEngine()` runs on this machine (or a fresh
one), InsightFace downloads the `buffalo_l` model (~280MB) from GitHub —
needs internet, takes roughly a minute. Subsequent runs use the cached
copy in `~/.insightface/models/`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_face_engine.py`:

```python
import insightface.data

from core.face_engine import FaceEngine, FaceResult


def test_extract_faces_detects_faces_in_sample_image():
    # Bundled with the insightface package itself — no need to version
    # a photo of a real person in this repo.
    img = insightface.data.get_image("t1")
    engine = FaceEngine()

    faces = engine.extract_faces(img)

    assert len(faces) >= 1
    face = faces[0]
    assert isinstance(face, FaceResult)
    assert face.embedding.shape == (512,)
    assert 0.0 <= face.det_score <= 1.0
    assert len(face.bbox) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_face_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.face_engine'`

- [ ] **Step 3: Implement `core/face_engine.py`**

```python
from dataclasses import dataclass

import numpy as np
from insightface.app import FaceAnalysis


@dataclass
class FaceResult:
    bbox: tuple[int, int, int, int]
    embedding: np.ndarray
    det_score: float


class FaceEngine:
    def __init__(self, det_size: tuple[int, int] = (640, 640)):
        self._app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
        self._app.prepare(ctx_id=0, det_size=det_size)

    def extract_faces(self, frame: np.ndarray) -> list[FaceResult]:
        faces = self._app.get(frame)
        return [
            FaceResult(
                bbox=tuple(int(v) for v in face.bbox),
                embedding=face.normed_embedding,
                det_score=float(face.det_score),
            )
            for face in faces
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_face_engine.py -v`
Expected: 1 passed (first run downloads the model — see note above;
you'll see a progress bar and a `FutureWarning` from inside
`insightface`'s own alignment code, which is harmless and not ours to fix)

- [ ] **Step 5: Commit**

```bash
git add core/face_engine.py tests/test_face_engine.py
git commit -m "Add FaceEngine wrapping InsightFace detection and embeddings"
```

---

## Task 4: `apps/enroll.py` — enrollment CLI

**Files:**
- Create: `apps/enroll.py`
- Test: `tests/test_enroll.py`

**Interfaces:**
- Consumes: `core.face_engine.FaceEngine`, `core.face_engine.FaceResult`,
  `core.identity_store.IdentityStore`, `core.config.{KNOWN_FACES_DIR,
  DB_PATH, DET_SIZE}`
- Produces: `enroll_from_directory(known_faces_dir: Path, engine:
  FaceEngine, store: IdentityStore) -> None` (testable core logic,
  does not call `store.save()`); `main()` CLI entry point runnable as
  `python -m apps.enroll`

- [ ] **Step 1: Write the failing test**

Create `tests/test_enroll.py`:

```python
import cv2
import insightface.data

from apps.enroll import enroll_from_directory
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore


def test_enroll_from_directory_reads_photos_and_stores_embeddings(tmp_path):
    img = insightface.data.get_image("t1")
    person_dir = tmp_path / "pessoa_teste"
    person_dir.mkdir()
    cv2.imwrite(str(person_dir / "foto1.jpg"), img)

    engine = FaceEngine()
    store = IdentityStore(db_path=str(tmp_path / "db"))

    enroll_from_directory(tmp_path, engine, store)

    assert "pessoa_teste" in store.embeddings
    assert len(store.embeddings["pessoa_teste"]) == 1
    assert store.embeddings["pessoa_teste"][0].shape == (512,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_enroll.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.enroll'`

- [ ] **Step 3: Implement `apps/enroll.py`**

```python
from pathlib import Path

import cv2

from core.config import DB_PATH, DET_SIZE, KNOWN_FACES_DIR
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore


def enroll_from_directory(known_faces_dir: Path, engine: FaceEngine, store: IdentityStore) -> None:
    for person_dir in sorted(known_faces_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        name = person_dir.name
        embeddings = []
        for photo_path in sorted(person_dir.glob("*")):
            frame = cv2.imread(str(photo_path))
            if frame is None:
                print(f"Aviso: não foi possível ler {photo_path}, pulando.")
                continue
            faces = engine.extract_faces(frame)
            if not faces:
                print(f"Aviso: nenhum rosto detectado em {photo_path}, pulando.")
                continue
            embeddings.append(faces[0].embedding)
        if embeddings:
            store.enroll(name, embeddings)
            print(f"{name}: {len(embeddings)} foto(s) cadastrada(s).")


def main() -> None:
    engine = FaceEngine(det_size=DET_SIZE)
    store = IdentityStore(DB_PATH)
    store.load()
    enroll_from_directory(Path(KNOWN_FACES_DIR), engine, store)
    store.save()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_enroll.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add apps/enroll.py tests/test_enroll.py
git commit -m "Add enroll.py CLI to build the identity database from reference photos"
```

- [ ] **Step 6: Manual validation with real photos (done by the project owner, not automatable)**

1. Create `data/known_faces/<seu_nome>/` and drop in a few of your own
   photos (the ones gitignored per Task 1).
2. Run: `.venv/bin/python -m apps.enroll`
3. Expected: console prints `<seu_nome>: N foto(s) cadastrada(s).` for
   each photo successfully enrolled, and `data/identity_db.npz` +
   `data/identity_db.json` are created.

---

## Task 5: `apps/webcam_demo.py` — live recognition CLI

**Files:**
- Create: `apps/webcam_demo.py`

**Interfaces:**
- Consumes: `core.face_engine.FaceEngine.extract_faces`,
  `core.identity_store.IdentityStore.{load, match}`,
  `core.config.{CAMERA_INDEX, DB_PATH, DET_SIZE, SIMILARITY_THRESHOLD}`
- Produces: CLI entry point runnable as `python -m apps.webcam_demo
  [--source SOURCE]`, where `SOURCE` is a camera index (default from
  config) or a path to a recorded video file.

This task is orchestration glue over already-tested `core/` logic (frame
capture loop, drawing, keyboard handling) — per the spec, its correctness
is validated manually with a live camera and a recorded video, not by an
automated test.

- [ ] **Step 1: Implement `apps/webcam_demo.py`**

```python
import argparse

import cv2

from core.config import CAMERA_INDEX, DB_PATH, DET_SIZE, SIMILARITY_THRESHOLD
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default=str(CAMERA_INDEX),
        help="Índice da câmera (ex: 0) ou caminho de um arquivo de vídeo",
    )
    args = parser.parse_args()
    source = int(args.source) if args.source.isdigit() else args.source

    engine = FaceEngine(det_size=DET_SIZE)
    store = IdentityStore(DB_PATH)
    store.load()

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Não foi possível abrir a fonte de vídeo: {source}")

    print("Pressione 'q' para sair.")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for face in engine.extract_faces(frame):
            name, score = store.match(face.embedding, SIMILARITY_THRESHOLD)
            label = f"{name} ({score:.2f})" if name else "Desconhecido"
            x1, y1, x2, y2 = face.bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 10, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
        cv2.imshow("Reconhecimento facial", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add apps/webcam_demo.py
git commit -m "Add webcam_demo.py CLI for live/recorded-video face recognition"
```

- [ ] **Step 3: Manual validation — live webcam (done by the project owner)**

1. Make sure `data/identity_db.npz` exists (Task 4's manual step ran
   first).
2. If on WSL2, set up `usbipd-win` to pass the webcam through, or run
   this step natively on Windows/Linux instead.
3. Run: `.venv/bin/python -m apps.webcam_demo`
4. Expected: a window opens showing the camera feed; your face gets a
   green box and your enrolled name once InsightFace recognizes it;
   unknown faces show "Desconhecido"; `q` closes the window.

- [ ] **Step 4: Manual validation — recorded video (repeatable regression check)**

1. Record a short `.mp4`/`.avi` clip (webcam or phone) with enrolled and
   non-enrolled people in frame.
2. Run: `.venv/bin/python -m apps.webcam_demo --source path/to/clip.mp4`
3. Expected: same overlay behavior as the live case, so this clip can be
   re-run after future changes to catch regressions.
