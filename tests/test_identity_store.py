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


def test_db_path_includes_model_name(tmp_path):
    db_path = str(tmp_path / "identity_db")
    store = IdentityStore(db_path, model_name="buffalo_s")
    assert store.db_path.name == "identity_db_buffalo_s"


def test_different_models_use_separate_db_files(tmp_path):
    db_path = str(tmp_path / "identity_db")

    store_l = IdentityStore(db_path, model_name="buffalo_l")
    store_l.enroll("alice", [np.array([1.0, 0.0, 0.0], dtype=np.float32)])
    store_l.save()

    store_s = IdentityStore(db_path, model_name="buffalo_s")
    store_s.load()

    assert store_s.embeddings == {}


def test_centroid_is_not_fooled_by_one_outlier_photo():
    # 3 fotos de alice apontando p/ x; 1 foto ruim de alice quase igual a bob (y).
    store = IdentityStore(db_path="unused")  # centroid é o padrão
    store.enroll("alice", [np.array([1.0, 0.0, 0.0])] * 3 + [np.array([0.05, 1.0, 0.0])])
    store.enroll("bob", [np.array([0.2, 0.98, 0.0])])
    query = np.array([0.0, 1.0, 0.0])  # é o bob (foto de cadastro dele é só parecida)

    name_centroid, _ = store.match(query, threshold=0.5)
    store_max = IdentityStore(db_path="unused", aggregation="max")
    store_max.embeddings = store.embeddings
    name_max, _ = store_max.match(query, threshold=0.5)

    assert name_centroid == "bob"
    assert name_max == "alice"  # o máximo pega a foto ruim da alice: falsa identificação


def test_enroll_rejects_zero_embedding():
    store = IdentityStore(db_path="unused")
    with pytest.raises(ValueError):
        store.enroll("alice", [np.zeros(3)])


def test_db_path_pointing_to_dot_is_rejected():
    with pytest.raises(ValueError):
        IdentityStore(db_path=".")


def test_scores_match_loop_cosine_for_both_aggregations():
    rng = np.random.default_rng(0)
    people = {f"p{i}": [rng.normal(size=64) for _ in range(3)] for i in range(20)}
    query = rng.normal(size=64)
    for agg in ("centroid", "max"):
        store = IdentityStore(db_path="unused", aggregation=agg)
        for n, embs in people.items():
            store.enroll(n, embs)
        got = store.scores(query)
        for n, embs in people.items():
            unit = [e / np.linalg.norm(e) for e in embs]
            if agg == "centroid":
                c = np.mean(unit, axis=0)
                expected = cosine_similarity(query, c)
            else:
                expected = max(cosine_similarity(query, e) for e in unit)
            assert got[n] == pytest.approx(expected, abs=1e-6)


def test_degenerate_query_is_unknown_not_exception():
    store = IdentityStore(db_path="unused")
    store.enroll("alice", [np.array([1.0, 0.0, 0.0])])
    assert store.match(np.zeros(3), threshold=0.5) == (None, 0.0)
    assert store.match(np.array([np.nan, 0.0, 0.0]), threshold=0.5) == (None, 0.0)


def test_enroll_with_no_embeddings_creates_nothing_and_does_not_break_match():
    store = IdentityStore(db_path="unused")
    store.enroll("alice", [np.array([1.0, 0.0, 0.0])])
    store.enroll("vazio", [])
    assert "vazio" not in store.embeddings
    assert store.match(np.array([1.0, 0.0, 0.0]), threshold=0.5)[0] == "alice"


def test_load_skips_invalid_legacy_embeddings_without_partial_state(tmp_path, capsys):
    db_path = str(tmp_path / "db")
    np.savez(
        IdentityStore(db_path).db_path.with_suffix(".npz"),
        names=np.array(["alice", "ruim", "bob"]),
        embeddings=np.stack([np.array([1.0, 0, 0]), np.zeros(3), np.array([0, 1.0, 0])]),
    )
    store = IdentityStore(db_path)
    store.load()
    assert set(store.embeddings) == {"alice", "bob"}
    assert "1 embedding(s) inválido(s)" in capsys.readouterr().err
    assert store.match(np.array([0, 1.0, 0]), threshold=0.5)[0] == "bob"
