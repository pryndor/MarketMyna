"""Chinese -> English names: glossary/pinyin text and cached stock names."""

from src.services import translate as tr


def test_english_text_brokers_and_pinyin():
    assert tr.english_text("机构专用") == "Institutional seat"
    out = tr.english_text("华泰证券股份有限公司上海浦东新区滨江大道证券营业部")
    assert out.startswith("Huatai Securities") and "Shanghai" in out and out.endswith("branch")
    assert tr.english_text("Tencent") == "Tencent"


def test_clean_company():
    assert tr.clean_company("Contemporary Amperex Technology Co., Limited") == "Contemporary Amperex Technology"
    assert tr.clean_company("Kweichow Moutai Co., Ltd.") == "Kweichow Moutai"
    assert tr.clean_company("PetroChina Company Limited") == "PetroChina"


def test_english_names_cache_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "_path", lambda: tmp_path / "names.json")
    monkeypatch.setattr(tr, "_names", None)
    calls = []

    def lookup(yahoo):
        calls.append(yahoo)
        return "CATL" if yahoo == "300750.SZ" else None

    items = [("300750", "宁德时代"), ("920000", "安徽凤")]
    out = tr.english_names(items, "china_a", lookup=lookup)
    assert out["300750"] == "CATL" and out["920000"] == "Anhui Feng"
    assert calls[0] == "300750.SZ" and len(calls) == 2
    tr.english_names(items, "china_a", lookup=lookup)
    assert len(calls) == 2  # cached
    assert (tmp_path / "names.json").exists()
