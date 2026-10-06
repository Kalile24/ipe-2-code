from pathlib import Path

from core import config


def test_known_faces_dir_is_absolute_and_under_repo_root():
    repo_root = Path(__file__).resolve().parent.parent
    assert Path(config.KNOWN_FACES_DIR).is_absolute()
    assert Path(config.KNOWN_FACES_DIR) == repo_root / "data" / "known_faces"


def test_db_path_is_absolute_and_under_repo_root():
    repo_root = Path(__file__).resolve().parent.parent
    assert Path(config.DB_PATH).is_absolute()
    assert Path(config.DB_PATH) == repo_root / "data" / "identity_db"


def test_model_root_comes_from_insightface_root_env(monkeypatch):
    import importlib

    from core import config

    monkeypatch.setenv("INSIGHTFACE_ROOT", "/opt/insightface")
    importlib.reload(config)
    assert config.MODEL_ROOT == "/opt/insightface"
    monkeypatch.delenv("INSIGHTFACE_ROOT")
    importlib.reload(config)
    assert config.MODEL_ROOT is None
