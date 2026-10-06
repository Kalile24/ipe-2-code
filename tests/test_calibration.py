import numpy as np

from core.calibration import leave_one_out


def _db():
    rng = np.random.default_rng(1)
    base = {n: rng.normal(size=64) for n in ("alice", "bob", "carol")}
    return {n: [base[n] + rng.normal(scale=0.3, size=64) for _ in range(4)] for n in base}


def test_leave_one_out_counts_pairs():
    res = leave_one_out(_db())
    assert len(res.genuine) == 12          # 3 pessoas x 4 fotos
    assert len(res.impostor) == 12 * 2     # cada probe vs. as outras 2
    assert res.skipped == []


def test_genuine_scores_exceed_impostor_scores_on_separable_data():
    res = leave_one_out(_db())
    assert min(res.genuine) > max(res.impostor)
    lo, hi = res.safe_interval()
    t = res.suggest()
    assert lo < t < hi
    assert res.table([t]) == [(t, 0.0, 0.0)]


def test_overlapping_distributions_give_no_suggestion():
    rng = np.random.default_rng(3)
    db = {n: [rng.normal(size=8) for _ in range(3)] for n in ("a", "b", "c")}  # ruído puro
    res = leave_one_out(db)
    assert res.safe_interval() is None and res.suggest() is None


def test_single_photo_identities_are_reported_not_calibrated():
    db = _db()
    db["dave"] = [np.ones(64)]
    res = leave_one_out(db)
    assert res.skipped == ["dave"]
    assert len(res.impostor) == 12 * 3  # dave ainda conta como impostor para os outros
