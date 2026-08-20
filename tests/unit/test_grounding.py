from models.schemas import Issue
from services.grounding import ground_issue, ground_issues

SOURCE = """
function checkBudget(tx) {
  const overspendCategory = tx.category;
  return overspendCategory;
}
"""


def test_hallucinated_identifier_is_rejected():
    issue = Issue(
        line=3,
        category="logic",
        issue="overshootCategory is undefined",
        evidence="const overshootCategory = tx.category;",
        source="ai_quality",
    )
    grounded, reason = ground_issue(issue, SOURCE)
    assert grounded is False
    assert "overshootcategory" in reason


def test_real_evidence_exact_substring_is_grounded():
    issue = Issue(
        line=3,
        category="logic",
        issue="real finding",
        evidence="const overspendCategory = tx.category;",
        source="ai_quality",
    )
    grounded, reason = ground_issue(issue, SOURCE)
    assert grounded is True
    assert reason == ""


def test_paraphrased_evidence_with_real_identifiers_is_grounded():
    issue = Issue(
        line=3,
        category="logic",
        issue="real finding, paraphrased",
        evidence="the overspendCategory variable is returned",
        source="ai_quality",
    )
    grounded, _ = ground_issue(issue, SOURCE)
    assert grounded is True


def test_line_out_of_range_is_rejected():
    issue = Issue(
        line=999,
        category="logic",
        issue="x",
        evidence="const overspendCategory = tx.category;",
        source="ai_quality",
    )
    grounded, reason = ground_issue(issue, SOURCE)
    assert grounded is False
    assert "outside the source range" in reason


def test_ai_finding_with_no_evidence_is_rejected():
    issue = Issue(line=3, category="logic", issue="x", evidence="", source="ai_quality")
    grounded, reason = ground_issue(issue, SOURCE)
    assert grounded is False
    assert "no evidence" in reason


def test_deterministic_finding_without_evidence_is_not_penalized():
    # Deterministic findings already carry real evidence in practice (the
    # regex rule wouldn't have fired otherwise) -- this only checks that the
    # grounding gate doesn't apply the same "AI must justify itself" bar to
    # a different source of finding.
    issue = Issue(line=3, category="logic", issue="x", evidence="", source="deterministic")
    grounded, _ = ground_issue(issue, SOURCE)
    assert grounded is True


def test_ground_issues_splits_grounded_and_rejected():
    good = Issue(line=3, category="logic", issue="ok", evidence="overspendCategory", source="ai_quality")
    bad = Issue(line=3, category="logic", issue="bad", evidence="overshootCategory", source="ai_quality")
    grounded, rejected = ground_issues([good, bad], SOURCE)
    assert grounded == [good]
    assert len(rejected) == 1
    assert rejected[0]["issue"] == "bad"
