import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_selfaudit_grades_yesterday(tmp_path, monkeypatch):
    import sentinel.selfaudit as sa
    from sentinel.store import Store
    log = tmp_path / "blog.jsonl"
    monkeypatch.setattr(sa, "LOG", log)
    store = Store(str(tmp_path / "t.db"))
    sa.append_bulletin_log("2026-10-13", ["Ahmad Yani"], [],
                           ["Baratan"], ["Pertalite"])
    # today: Ahmad Yani still bad (60), Baratan still fine (5)
    for code, score in (("54.681.25", 60), ("54.681.06", 5)):
        store.conn.execute(
            "INSERT INTO station_scores(run_id, ts, station_code,"
            " crisis_score, confidence, detail) VALUES (1,'t',?,? ,0.5,"
            " '{}')", (code, score))
    store.conn.commit()
    rep = sa.run(store, {})
    assert rep["graded_days"] == 1, rep
    g = rep["latest_grade"]
    assert g["avoid_precision"] == 1.0 and g["fine_stability"] == 1.0
    # second run same day: no double grading
    rep2 = sa.run(store, {})
    assert rep2["graded_days"] == 1
