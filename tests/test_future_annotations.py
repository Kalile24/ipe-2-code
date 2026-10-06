import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = [
    REPO_ROOT / "core",
    REPO_ROOT / "apps",
    REPO_ROOT / "scripts",
    REPO_ROOT / "ros2_ws" / "src" / "face_recognition_ros" / "face_recognition_ros",
]


def _modules():
    for d in SOURCE_DIRS:
        for path in sorted(d.glob("*.py")):
            if path.name != "__init__.py":
                yield path


def _has_future_annotations(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return any(alias.name == "annotations" for alias in node.names)
    return False


def test_every_module_defers_annotation_evaluation():
    # O PC2 de fábrica do Unitree G1 roda Python 3.8 (JetPack 5.1.1, ver
    # docs/superpowers/specs/2026-09-18-jetson-gpu-migration-design.md). Sem este import,
    # `str | None` e `list[int]` em assinaturas quebram na importação com TypeError.
    missing = [str(p.relative_to(REPO_ROOT)) for p in _modules() if not _has_future_annotations(p)]
    assert missing == [], f"sem `from __future__ import annotations`: {missing}"


def test_modules_parse_as_python_38_syntax():
    # Alcance limitado: `feature_version` só rejeita sintaxe nova (ex.: `match`); NÃO pega
    # `X = tuple[int, int]` fora de anotação nem `{} | {}`, que quebram em 3.8 em tempo de
    # execução. A prova real é o job 3.8 do workflow importando e testando os módulos puros.
    for path in _modules():
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 8))
