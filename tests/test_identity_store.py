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
