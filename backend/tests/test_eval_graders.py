"""
tests/test_eval_graders.py — the web-search eval's code graders (#54, evals/graders.py).

These graders decide the eval's numbers, so a bug here would silently mislead every comparison
between prompts and models. Each test builds a CaseRun by hand (no model, no Tavily, $0).
"""

import json
from datetime import date

from evals.graders import (
    CaseRun,
    CriterionGrade,
    RubricGrade,
    grade_decision,
    grade_freshness,
    grade_grounding,
    grade_query,
    judge_prompt,
    rubric_scores,
)

TODAY = date(2026, 9, 29)
NEWS_CASE = {"question": "AI news today?", "should_search": True, "freshness": "day", "rubric": ["Has three items.", "Every item has a link."]}
TIMELESS_CASE = {"question": "Why is the sky blue?", "should_search": False, "freshness": "none", "rubric": ["Explains scattering."]}


def tavily(*results: dict) -> str:
    """One search result as the model receives it: Tavily's JSON inside Simba's untrusted fence."""
    return f"<untrusted_tool_result>\n{json.dumps({'results': list(results)})}\n</untrusted_tool_result>"


def test_decision_rewards_searching_only_when_needed():
    """Searching for news and not searching for a timeless question both score 1; the opposite, 0."""
    searched = CaseRun(answer="", tool_calls=[{"query": "AI news"}])
    silent = CaseRun(answer="")
    assert grade_decision(NEWS_CASE, searched) == 1
    assert grade_decision(NEWS_CASE, silent) == 0
    assert grade_decision(TIMELESS_CASE, silent) == 1
    assert grade_decision(TIMELESS_CASE, searched) == 0


def test_query_needs_news_topic_fitting_range_and_no_guessed_year():
    """The #52 bug in numbers: a general search, a missing time range or "2024" in the query all fail."""
    def query(**args):
        return grade_query(NEWS_CASE, CaseRun(answer="", tool_calls=[args]), TODAY)

    assert query(query="AI news", topic="news", time_range="day") == 1
    assert query(query="AI news 2026", topic="news", time_range="day") == 1  # this year is fine
    assert query(query="AI news 2024", topic="news", time_range="day") == 0
    assert query(query="AI news", topic="general", time_range="day") == 0
    assert query(query="AI news", topic="news") == 0
    assert grade_query(NEWS_CASE, CaseRun(answer=""), TODAY) == 0  # no search at all
    assert grade_query(TIMELESS_CASE, CaseRun(answer=""), TODAY) is None  # doesn't apply


def test_freshness_is_the_share_of_results_dated_in_the_window():
    """Two fresh results out of four -> 0.5; an undated result can't count as fresh."""
    run = CaseRun(answer="", tool_results=[tavily(
        {"url": "https://a.test", "published_date": "Tue, 29 Sep 2026 08:00:00 GMT"},
        {"url": "https://b.test", "published_date": "2026-09-28"},
        {"url": "https://c.test", "published_date": "Wed, 15 Jan 2025 10:00:00 GMT"},
        {"url": "https://d.test"},
    )])
    assert grade_freshness(NEWS_CASE, run, TODAY) == 0.5
    assert grade_freshness(NEWS_CASE, CaseRun(answer=""), TODAY) == 0.0
    assert grade_freshness(TIMELESS_CASE, run, TODAY) is None


def test_freshness_reads_results_cut_off_mid_json():
    """web_search.py caps results at 8,000 characters, so the JSON often ends mid-way. The grader
    must still read the dates it can see instead of scoring the case 0."""
    cut = tavily({"url": "https://a.test", "published_date": "2026-09-29"}, {"url": "https://b.test", "content": "x" * 50})[:-60]
    assert grade_freshness(NEWS_CASE, CaseRun(answer="", tool_results=[cut]), TODAY) == 0.5


def test_grounding_fails_a_link_that_was_not_in_the_results():
    """A link the model made up (or remembered) is caught; trailing punctuation doesn't matter."""
    results = [tavily({"url": "https://news.test/story"})]
    assert grade_grounding(CaseRun(answer="See (https://news.test/story).", tool_results=results)) == 1
    assert grade_grounding(CaseRun(answer="See https://made-up.test/x", tool_results=results)) == 0
    assert grade_grounding(CaseRun(answer="No links here.")) == 1


def test_rubric_scores_match_verdicts_by_position():
    """Verdicts belong to items by order; one pass and one fail -> not all passed, share 0.5."""
    grade = RubricGrade(criteria=[CriterionGrade(passed=True, reason="three items"),
                                  CriterionGrade(passed=False, reason="no links")])
    passed, share, reasons = rubric_scores(NEWS_CASE, grade)
    assert (passed, share) == (0, 0.5)
    assert reasons["2. Every item has a link."] == "FAIL: no links"


def test_rubric_scores_refuse_a_reply_with_the_wrong_number_of_verdicts():
    """If the judge answers 1 of 2 items, no verdict can be trusted to sit on its item: the case is
    not scored at all (None), rather than scored wrongly. This happened in the first baseline."""
    grade = RubricGrade(criteria=[CriterionGrade(passed=True, reason="three items")])
    assert rubric_scores(NEWS_CASE, grade) is None


def test_judge_prompt_fences_the_graded_text_and_gives_the_date():
    """The judge must know today's date to check freshness, and see answer and results as data."""
    prompt = judge_prompt(NEWS_CASE, CaseRun(answer="Hello"), TODAY)
    assert "Today is Tuesday, 29 September 2026." in prompt
    assert "<answer>\nHello\n</answer>" in prompt
    assert "(no search was made)" in prompt
    assert "1. Has three items.\n2. Every item has a link." in prompt
