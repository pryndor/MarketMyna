"""JSON columns never store NaN / infinity: they are not valid JSON (other
readers of the saved report choke on them), so they are written as null."""

import math

from sqlalchemy import text

from marketmyna.storage import DatabaseManager, ReportRunRecord, json_dumps


def test_json_dumps_turns_non_finite_into_null():
    assert json_dumps({"price": math.nan, "rows": [1.5, math.inf, {"x": -math.inf}]}) == \
        '{"price": null, "rows": [1.5, null, {"x": null}]}'


def test_report_row_with_nan_price_saves_as_null(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 't.db'}")
    with db.get_session() as session:
        session.add(ReportRunRecord(token="t1", rows=[{"symbol": "ENERGY", "price": float("nan")}], meta={}))
        session.commit()
    with db.engine.connect() as conn:
        raw = conn.execute(text("select rows from report_runs")).scalar()
    assert "NaN" not in raw and '"price": null' in raw
