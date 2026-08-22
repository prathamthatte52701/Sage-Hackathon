"""Phase 3.3 certification: SEC-NOSQL-INJECTION.

Supported in this phase: a direct request-controlled object passed as the
filter to a recognized MongoDB/PyMongo collection or Mongoose model method.
This is intentionally local and direct only. Assignment/helper/cross-file
propagation belongs to Phase 4, and scalar field lookups are not findings.
"""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _nosql_findings(code: str, language: str = "python"):
    return [
        finding
        for finding in to_closed_world_findings(run_rules("repository/app.py", language, code))
        if finding["rule_id"] == "SEC-NOSQL-INJECTION"
    ]


# ---------------------------------------------------------------- positive

def test_mongoose_model_direct_request_body_filter_detected():
    findings = _nosql_findings("User.find(req.body)", "javascript")

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "SEC-NOSQL-INJECTION"
    assert findings[0]["cwe"] == "CWE-943"
    assert findings[0]["evidence"] in "User.find(req.body)"


def test_mongo_database_collection_direct_request_query_filter_detected():
    findings = _nosql_findings("db.users.updateOne(req.query, { $set: { role: 'user' } })", "javascript")

    assert len(findings) == 1


def test_named_collection_direct_request_body_filter_detected():
    findings = _nosql_findings("ordersCollection.deleteOne(request.body)", "javascript")

    assert len(findings) == 1


def test_pymongo_database_collection_direct_json_filter_detected():
    findings = _nosql_findings("db.users.find_one(request.get_json())")

    assert len(findings) == 1


def test_pymongo_named_collection_direct_args_filter_detected():
    findings = _nosql_findings("users_collection.delete_one(req.args)")

    assert len(findings) == 1


# ---------------------------------------------------------------- negative

def test_safe_scalar_mongoose_lookup_not_reported():
    assert _nosql_findings("User.findOne({ email: req.body.email })", "javascript") == []


def test_safe_scalar_pymongo_lookup_not_reported():
    assert _nosql_findings('db.users.find_one({"email": request.json["email"]})') == []


def test_static_mongoose_filter_not_reported():
    assert _nosql_findings("User.find({ active: true })", "javascript") == []


def test_non_database_javascript_find_is_not_reported():
    assert _nosql_findings("items.find(req.body)", "javascript") == []


def test_non_database_python_find_is_not_reported():
    assert _nosql_findings("items.find(request.json)") == []


def test_unknown_receiver_is_not_reported():
    assert _nosql_findings("search.find(req.body)", "javascript") == []


def test_request_object_in_comment_or_string_is_not_reported():
    assert _nosql_findings("// User.find(req.body)", "javascript") == []
    assert _nosql_findings('const docs = "User.find(req.body)"', "javascript") == []
    assert _nosql_findings("# db.users.find_one(request.json)") == []
    assert _nosql_findings('docs = "db.users.find_one(request.json)"') == []


def test_local_propagation_is_not_claimed_before_phase_four():
    code = "filter = request.get_json()\ndb.users.find_one(filter)"
    assert _nosql_findings(code) == []


# -------------------------------------------------------------- adversarial

def test_fake_sanitizer_name_does_not_make_a_direct_raw_filter_safe():
    code = "def sanitize_filter(value):\n    return value\ndb.users.find_one(request.get_json())"
    assert len(_nosql_findings(code)) == 1


def test_multiple_direct_filters_produce_one_finding_each():
    code = "User.find(req.body)\nOrder.findOne(req.query)"
    assert len(_nosql_findings(code, "javascript")) == 2


# ---------------------------------------------------------- determinism/gate

def test_nosql_finding_is_deterministic_across_repeated_analysis():
    code = "db.users.find_one(request.get_json())"
    results = [_nosql_findings(code) for _ in range(10)]

    assert all(result == results[0] for result in results)
    assert results[0][0]["file"] == "repository/app.py"
    assert results[0][0]["line"] == 1
