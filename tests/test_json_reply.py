"""Tolerant JSON reading of model replies (marketmyna/llm/json_reply.py)."""

from marketmyna.llm.json_reply import parse_object

# Shape of the real reply that broke the fund review: gpt-oss ran out of
# tokens mid-way through "sections".
TRUNCATED = ('{ "summary": "Strong risk-adjusted returns, outpacing the Nifty 500.", '
             '"strengths": ["Low beta (0.58)", "Rank 1 on Sharpe"], "concerns": ["Lags in strong rallies"], '
             '"sections": { "returns": "Median 1-yr return 18% vs 11.8%.", "risk": "beating the benchmark in ~55-60% of windows')


def test_cut_off_reply_keeps_the_finished_fields():
    data = parse_object(TRUNCATED)
    assert data["summary"].startswith("Strong") and data["strengths"] == ["Low beta (0.58)", "Rank 1 on Sharpe"]
    assert data["sections"] == {"returns": "Median 1-yr return 18% vs 11.8%."}  # half-written "risk" dropped


def test_fenced_and_wrapped_replies():
    assert parse_object('```json\n{"summary": "ok", "n": [1, 2]}\n```') == {"summary": "ok", "n": [1, 2]}
    assert parse_object('Here you go: {"summary": "a {brace} inside"} hope it helps') == {"summary": "a {brace} inside"}


def test_cut_inside_a_list_and_escaped_quotes():
    assert parse_object('{"summary": "say \\"hi\\"", "points": ["one", "tw') == {"summary": 'say "hi"', "points": ["one"]}


def test_nothing_usable():
    assert parse_object("no json at all") is None
    assert parse_object('{"summary": "never closed') is None
    assert parse_object("{'single': 'quotes'}") is None
