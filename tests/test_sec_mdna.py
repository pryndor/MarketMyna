"""Tests for SEC MD&A extraction (offline)."""

import pytest

from src.services import sec_mdna

BODY = "Revenue grew 12% to $10.2 billion driven by services. " * 60


def test_extract_skips_table_of_contents():
    text = ("Table of Contents\nItem 7. Management's Discussion and Analysis 25\nItem 7A. Quantitative 40\n"
            f"...\nItem 7. Management’s Discussion and Analysis of Financial Condition\n{BODY}\n"
            "Item 7A. Quantitative and Qualitative Disclosures About Market Risk\nrates...")
    out = sec_mdna.extract_mdna(text, "10-K")
    assert out.startswith("Item 7. Management’s Discussion") and "Revenue grew 12%" in out and "Item 7A" not in out


def test_extract_10q_and_missing():
    text = f"Item 2. Management's Discussion and Analysis\n{BODY}\nItem 3. Quantitative and Qualitative"
    assert "services" in sec_mdna.extract_mdna(text, "10-Q")
    with pytest.raises(ValueError):
        sec_mdna.extract_mdna("Item 2. Management's Discussion\nshort\nItem 3. Quantitative", "10-Q")


def test_html_to_text_drops_hidden_and_scripts():
    html = "<html><script>x=1</script><div style='display:none'>XBRL junk</div><p>Item&nbsp;7.</p><p>Hello</p></html>"
    text = sec_mdna.html_to_text(html)
    assert "Hello" in text and "XBRL junk" not in text and "x=1" not in text and "Item 7." in text


def test_user_agent_required(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(sec_mdna.SecNotConfigured):
        sec_mdna.user_agent()
    monkeypatch.setenv("SEC_USER_AGENT", "MarketMyna ops@example.com")
    assert sec_mdna.user_agent() == "MarketMyna ops@example.com"


def test_latest_filing_picks_first_10k_or_10q(monkeypatch):
    class R:
        def json(self):
            return {"filings": {"recent": {"form": ["8-K", "10-Q", "10-K"], "filingDate": ["a", "2026-08-01", "c"],
                                           "reportDate": ["", "2026-06-30", ""], "accessionNumber": ["1", "2", "3"],
                                           "primaryDocument": ["x", "q.htm", "k.htm"]}}}

    monkeypatch.setattr(sec_mdna, "_get", lambda url: R())
    f = sec_mdna.latest_filing(320193)
    assert f["form"] == "10-Q" and f["document"] == "q.htm" and f["period"] == "2026-06-30"
