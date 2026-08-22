from routers.review import _build_transform_response


def test_paste_fix_response_marks_exact_single_match_applyable():
    code = "async function save(user) {\n  pendingUser = user;\n  await api.save(user);\n}\n"
    parsed = {
        "original_snippet": "pendingUser = user;\n  await api.save(user);",
        "proposed_fix": "pendingUser = user;\n  try {\n    await api.save(user);\n  } finally {\n    pendingUser = null;\n  }",
        "explanation": "Clear pendingUser in finally so success and failure reset state.",
        "confidence": 0.86,
    }
    issue = {"line": 2, "rule": "paste_quality_issue", "category": "logic"}

    fix = _build_transform_response(parsed, issue, code)

    assert fix.can_apply is True
    assert fix.apply_failure_reason == ""
    assert fix.target_file == "fixed-code"
    assert fix.document_type == "paste"
    assert fix.source_hash
    assert fix.start_line == 2
    assert fix.end_line == 3
    assert "finally" in fix.fixed_code


def test_paste_fix_response_reports_specific_failure_reason():
    code = "const value = 1;\n"
    parsed = {
        "original_snippet": "const missing = 1;",
        "proposed_fix": "const missing = 2;",
        "explanation": "Update the value.",
        "confidence": 0.8,
    }

    fix = _build_transform_response(parsed, {"line": 1, "category": "logic"}, code)

    assert fix.can_apply is False
    assert fix.apply_failure_reason == "target_not_found"


def test_pending_user_fix_prefers_finally_cleanup():
    code = "async function saveUser(user) {\n  pendingUser = user;\n  await api.saveUser(user);\n  notifySaved(user.id);\n}\n"
    parsed = {
        "original_snippet": "  pendingUser = user;\n  await api.saveUser(user);\n  notifySaved(user.id);",
        "proposed_fix": (
            "  pendingUser = user;\n"
            "  try {\n"
            "    await api.saveUser(user);\n"
            "    notifySaved(user.id);\n"
            "  } catch (e) {\n"
            "    pendingUser = null;\n"
            "    throw e;\n"
            "  }"
        ),
        "explanation": "Clear pendingUser when saving fails.",
        "confidence": 0.8,
    }
    issue = {
        "line": 2,
        "category": "logic",
        "issue": "pendingUser is not cleared if saveUser fails",
        "fix_suggestion": "Prefer clearing pendingUser in finally so it is reset on both success and failure.",
    }

    fix = _build_transform_response(parsed, issue, code)

    assert fix.can_apply is True
    assert "finally" in fix.proposed_fix
    assert "catch" not in fix.proposed_fix
