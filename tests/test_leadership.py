"""CEO / leadership snapshot - pure helpers, no network."""

import pytest

from marketmyna.services import leadership

INFO = {
    "longName": "Apple Inc.",
    "financialCurrency": "USD",
    "companyOfficers": [
        {"name": "Mr. Timothy D. Cook", "title": "Executive Chairman of the Board", "age": 64, "totalPay": 16759518},
        {"name": "Mr. Kevan  Parekh", "title": "Senior VP & CFO", "age": 53, "totalPay": 4034174},
        {"name": "Mr. John  Ternus", "title": "CEO & Director", "age": 50},
    ],
    "overallRisk": 1,
    "compensationRisk": 6,
    "governanceEpochDate": 1788220800,
}


def test_ceo_beats_executive_chairman():
    data = leadership.leadership_from_info(INFO)
    assert data["ceo"]["name"] == "Mr. John Ternus"
    assert [o["name"] for o in data["officers"]] == ["Mr. Timothy D. Cook", "Mr. Kevan Parekh"]
    assert [g["label"] for g in data["governance"]] == ["Overall", "Compensation"]
    assert data["governance_as_of"] == "2026-09-01"


def test_managing_director_counts_as_ceo():
    officers = [{"title": "Executive Director"}, {"title": "Chairman & MD"}]
    assert leadership.pick_ceo(officers) is officers[1]


def test_no_officers_raises():
    with pytest.raises(ValueError):
        leadership.leadership_from_info({"longName": "X"})


def test_parse_brief_tolerates_fences_and_bad_verdict():
    text = '```json\n{"introduction": "Hi", "achievements": ["a", ""], "pitfalls": ["p"], "verdict": "Great"}\n```'
    brief = leadership._parse_brief(text)
    assert brief["achievements"] == ["a"]
    assert brief["verdict"] == "uncertain"
    assert leadership._parse_brief("no json here") is None
