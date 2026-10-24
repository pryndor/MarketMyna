"""Mutual fund dip alerts: one alert per crossing, the deepest level, re-armed near the high."""

from types import SimpleNamespace

from src.core import tenant


def test_dip_rules_and_ladder_alerts(owner_env, monkeypatch):
    from src.services import mf_holdings, mf_lumpsum as ml

    asha = owner_env["client"]
    asha.post("/api/v1/portfolio", json={"name": "Funds", "currency": "INR"})
    for code in ("120716", "118989"):
        asha.post("/api/v1/portfolio/Funds/transactions",
                  json={"symbol": code, "transaction_type": "buy", "quantity": 10, "price": 100, "market": "MF"})
    assert asha.put("/api/v1/portfolio/Funds/dip-alerts", json={"levels": [4]}).status_code == 400  # not a choice
    r = asha.put("/api/v1/portfolio/Funds/dip-alerts", json={"levels": [5, 7.5, 10], "overrides": {"118989": []}})
    assert r.json()["levels"] == [5, 7.5, 10] and r.json()["overrides"] == {"118989": []}

    dips = {"120716": -0.08, "118989": -0.12}
    monkeypatch.setattr(mf_holdings, "latest", lambda code: {"name": f"Fund {code}", "category": "Equity Scheme"})
    monkeypatch.setattr(ml, "assess_fund", lambda code, *a, **k: {
        "status": "ok", "below_52w_high": dips[code], "level": "watch", "met": 2, "total": 4, "after_dips_1y": None})
    sent = []
    disp = SimpleNamespace(send_all=lambda message, title=None, purpose=None: sent.append(title))
    state = {}
    with tenant.user_scope(owner_env["owner_id"]):
        first = ml.check_levels(owner_env["config"], state, "a", disp)
        again = ml.check_levels(owner_env["config"], state, "a", disp)
        dips["120716"] = -0.105
        deeper = ml.check_levels(owner_env["config"], state, "a", disp)
        dips["120716"] = -0.01
        ml.check_levels(owner_env["config"], state, "a", disp)  # back near the high: re-arm
        dips["120716"] = -0.06
        rearmed = ml.check_levels(owner_env["config"], state, "a", disp)
    assert first == [("120716", 7.5)]          # 5 and 7.5 crossed at once: one alert, deepest level
    assert again == [] and deeper == [("120716", 10.0)] and rearmed == [("120716", 5.0)]
    assert all("118989" not in t for t in sent)  # its override turned % alerts off
