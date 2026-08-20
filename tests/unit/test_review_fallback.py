from routers.review import _deterministic_review_response


def test_review_fallback_returns_static_findings_when_ai_unavailable():
    response = _deterministic_review_response("eval(user_input)", "python", "model service")
    assert response.issues
    assert response.issues[0].severity == "critical"
    assert "AI reasoning unavailable" in response.summary


def test_review_fallback_does_not_invent_clean_issues():
    response = _deterministic_review_response("print('hello')", "python", "model service")
    assert response.issues == []
    assert response.summary.startswith("No deterministic issues found")
