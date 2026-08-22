"""Phase 2/3: automated regression benchmarks for the seven manually-tested
snippets. Deliberately end-to-end and NOT mocked -- these call the real
review() pipeline (real deterministic rules, real pre-review RAG, real Groq,
real grounding, real per-finding RAG) because the whole point is proving the
repaired pipeline behaves correctly on realistic code, not that a mock
returns what the test expects. Skips (not fails) when GROQ_KEYS/DB aren't
configured in a given environment.

Assertions are semantic-theme-based per the task's own guidance, not exact
prose or exact counts -- model wording varies run to run. No keyword hacks
are added to production code to make these pass; the themes are detected
by scanning the *existing* Issue fields (issue/evidence/fix_suggestion/
category) that the pipeline already produces.
"""

import pytest

from config import GROQ_API_KEYS
from db.mongo import get_db
from models.schemas import Issue
from routers.review import ReviewRequestIn, review

pytestmark = pytest.mark.asyncio


def _skip_if_unavailable():
    if not GROQ_API_KEYS:
        pytest.skip("GROQ_KEYS not configured in this environment")
    if get_db() is None:
        pytest.skip("MONGO_URL not configured in this environment")


def _finding_text(issue: Issue) -> str:
    return " ".join(
        str(getattr(issue, field, "") or "")
        for field in ("issue", "evidence", "fix_suggestion", "category", "rule")
    ).lower()


THEMES = {
    "auth_shared_identity": ["shared", "global", "every request", "all request", "same user", "single", "privilege"],
    "promise_recovery": ["pending", "promise", "rejected", "never reset", "reset", "stuck", "retry"],
    "cache_scaling": ["process-local", "in-memory", "cache", "single instance", "horizontal", "scale"],
    "money_precision": ["float", "precision", "number", "rounding", "cent", "decimal"],
    "opening_balance_validation": ["openingbalance", "opening balance", "negative", "validat"],
    "pagination": ["unbounded", "pagina", "limit", "all record", "entire collection", "no limit"],
    "objectid_validation": ["objectid", "invalid id", "malformed id", "cast error", "castError".lower()],
    "payload_allowlisting": ["allowlist", "mass assign", "req.body", "arbitrary field", "unvalidated field"],
    "error_leakage": ["stack trace", "err.message", "internal error", "leak", "expose"],
    "rename_consistency": ["consisten", "rename", "partial", "multi-document", "multiple document", "atomic", "transaction"],
    "credited_amount_validation": ["creditedamount", "finite", "nan", "isnan", "numeric"],
    "external_api_timeout": ["timeout", "hang", "indefinitely", "no timeout"],
    "third_party_privacy": ["privacy", "third-party", "third party", "sensitive", "financial data", "external ai", "llm"],
    "stale_cache": ["stale", "never expire", "never invalidat", "no expir", "cache invalidat"],
    "duplicate_generation": ["duplicate", "concurrent", "race", "in-flight", "simultaneous"],
    "malformed_json_handling": ["malformed", "json", "parse", "unexpected shape", "no error handling"],
    "date_validation": ["invalid date", "date valid", "month range", "out of range", "13", "overflow", "normali"],
    "async_db_error_handling": ["error handling", "unhandled", "catch", "reject", "crash", "no try"],
}


def _detected_themes(findings: list[Issue]) -> set[str]:
    detected = set()
    for issue in findings:
        text = _finding_text(issue)
        for theme, keywords in THEMES.items():
            if any(kw in text for kw in keywords):
                detected.add(theme)
    return detected


async def _run(code: str, language: str = "javascript") -> list[Issue]:
    response = await review(
        ReviewRequestIn(code=code, language=language, session_id="benchmark-test"),
        current_user={"_id": "test-user"},
    )
    return response.deterministic_findings + response.ai_quality_review


# ---------------------------------------------------------------- Benchmark 1

BENCHMARK_1_AUTH_MIDDLEWARE = """
let cachedUser = null;
let pendingLookup = null;

async function authMiddleware(req, res, next) {
  if (cachedUser) {
    req.user = cachedUser;
    return next();
  }
  if (pendingLookup) {
    try {
      req.user = await pendingLookup;
      return next();
    } catch (err) {
      return next(err);
    }
  }
  const token = req.headers.authorization;
  pendingLookup = db.users.findOne({ token: token });
  try {
    cachedUser = await pendingLookup;
    req.user = cachedUser;
    next();
  } catch (err) {
    next(err);
  }
}

module.exports = { authMiddleware };
"""


async def test_benchmark_1_auth_middleware():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_1_AUTH_MIDDLEWARE)
    assert findings, "expected at least one finding on this auth middleware"
    themes = _detected_themes(findings)
    expected = {"auth_shared_identity", "promise_recovery", "cache_scaling"}
    assert themes & expected, f"expected at least one of {expected}, detected {themes}"


# ---------------------------------------------------------------- Benchmark 2

BENCHMARK_2_ACCOUNT_SCHEMA = """
const mongoose = require('mongoose');

const accountSchema = new mongoose.Schema({
  owner: { type: String, required: true },
  balance: { type: Number, default: 0 },
  openingBalance: { type: Number },
  currency: { type: String, default: 'USD' },
});

accountSchema.index({ owner: 1 });

module.exports = mongoose.model('Account', accountSchema);
"""


async def test_benchmark_2_account_schema():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_2_ACCOUNT_SCHEMA)
    themes = _detected_themes(findings)
    assert themes & {"money_precision", "opening_balance_validation"}, (
        f"expected a money-precision or openingBalance-validation concern, detected {themes}"
    )
    # the single-field owner index's *selectivity/query-performance* is a
    # contextual, optional concern -- must not be force-reported as a
    # confirmed finding. (A DIFFERENT, legitimate concern about this same
    # index -- e.g. it's not marked unique, allowing duplicate accounts -- is
    # a real data-integrity finding and is NOT what this asserts against.)
    selectivity_findings = [
        f for f in findings
        if "index" in _finding_text(f) and any(kw in _finding_text(f) for kw in ("selectiv", "query performance", "low-cardinality", "low cardinality"))
    ]
    assert not selectivity_findings, f"the standalone owner index's selectivity should not be force-flagged, got {selectivity_findings}"


# ---------------------------------------------------------------- Benchmark 3

BENCHMARK_3_CLEAN_NOTIFICATION_SCHEMA = """
const mongoose = require('mongoose');

const notificationSchema = new mongoose.Schema({
  userId: { type: mongoose.Schema.Types.ObjectId, ref: 'User', required: true },
  message: { type: String, required: true, maxlength: 500 },
  read: { type: Boolean, default: false },
  createdAt: { type: Date, default: Date.now },
});

notificationSchema.index({ userId: 1, createdAt: -1 });

module.exports = mongoose.model('Notification', notificationSchema);
"""


async def test_benchmark_3_clean_schema_does_not_become_noisy():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_3_CLEAN_NOTIFICATION_SCHEMA)
    # 0 findings is an explicitly acceptable, good outcome. If any findings
    # exist, they must be low/contextual, not critical/high fabricated noise.
    high_severity = [f for f in findings if f.severity in ("critical",) or (f.severity == "medium" and f.confidence > 0.7)]
    assert not high_severity, f"clean schema should not produce confident high-severity findings, got {high_severity}"


# ---------------------------------------------------------------- Benchmark 4

BENCHMARK_4_EXPRESS_CRUD_ROUTER = """
const router = require('express').Router();

router.get('/items', async (req, res) => {
  const items = await Item.find({});
  res.json(items);
});

router.get('/items/:id', async (req, res) => {
  const item = await Item.findById(req.params.id);
  res.json(item);
});

router.post('/items', async (req, res) => {
  const item = await Item.create(req.body);
  res.json(item);
});

router.delete('/items/:id', async (req, res) => {
  try {
    await Item.findByIdAndDelete(req.params.id);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
"""


async def test_benchmark_4_express_crud_router():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_4_EXPRESS_CRUD_ROUTER)
    themes = _detected_themes(findings)
    expected = {"pagination", "objectid_validation", "payload_allowlisting", "error_leakage", "async_db_error_handling"}
    assert themes & expected, f"expected at least one of {expected}, detected {themes}"

    # negative assertion: no prototype pollution claim without real evidence
    # of prototype mutation (this snippet has none -- Item.create(req.body)
    # is mass-assignment risk, not proven __proto__ mutation)
    pollution_findings = [f for f in findings if "prototype pollution" in _finding_text(f)]
    assert not pollution_findings, f"no prototype mutation evidence exists in this snippet, got {pollution_findings}"


# ---------------------------------------------------------------- Benchmark 5

BENCHMARK_5_LARGE_BUDGET_ROUTES = """
const router = require('express').Router();

router.post('/budgets/:id/rename', async (req, res) => {
  const budget = await Budget.findById(req.params.id);
  budget.name = req.body.name;
  const relatedTx = await Transaction.find({ budgetName: budget.name });
  for (const tx of relatedTx) {
    tx.budgetName = req.body.name;
    await tx.save();
  }
  await budget.save();
  res.json(budget);
});

router.post('/budgets/:id/credit', async (req, res) => {
  const budget = await Budget.findById(req.params.id);
  budget.creditedAmount = req.body.creditedAmount;
  await budget.save();
  res.json(budget);
});

router.get('/budgets/:id/transactions', async (req, res) => {
  const txs = await Transaction.find({ budgetId: req.params.id });
  res.json(txs);
});

module.exports = router;
"""


async def test_benchmark_5_large_budget_routes_not_zero_findings():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_5_LARGE_BUDGET_ROUTES)
    # Core assertion: this must NOT be zero, proving quality review is
    # actually inspecting semantics rather than only regex rules (which
    # find nothing in this snippet -- no eval/secrets/shell/sql-concat).
    assert findings, "expected AI quality review to surface concerns regex rules alone would miss"
    themes = _detected_themes(findings)
    expected = {
        "rename_consistency", "objectid_validation", "credited_amount_validation",
        "pagination", "async_db_error_handling",
    }
    assert themes & expected, f"expected at least one of {expected}, detected {themes}"


# ---------------------------------------------------------------- Benchmark 6

BENCHMARK_6_GROQ_INSIGHTS = """
const insightCache = {};

async function generateInsights(userId, transactions) {
  if (insightCache[userId]) {
    return insightCache[userId];
  }
  const prompt = "Analyze these transactions and their overspendCategory: " + JSON.stringify(transactions);
  const response = await fetch('https://api.groq.com/v1/chat', {
    method: 'POST',
    body: JSON.stringify({ prompt: prompt }),
  });
  const data = await response.json();
  insightCache[userId] = data.insights;
  return data.insights;
}

module.exports = { generateInsights };
"""


async def test_benchmark_6_groq_insights():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_6_GROQ_INSIGHTS)
    themes = _detected_themes(findings)
    expected = {"external_api_timeout", "third_party_privacy", "stale_cache", "duplicate_generation", "malformed_json_handling"}
    assert themes & expected, f"expected at least one of {expected}, detected {themes}"

    # CRITICAL negative assertion: source contains "overspendCategory" --
    # the reviewer must never invent "overshootCategory" or any other
    # nonexistent identifier anywhere in its findings.
    all_text = " ".join(_finding_text(f) for f in findings)
    assert "overshootcategory" not in all_text, "reviewer hallucinated a nonexistent identifier"


# ---------------------------------------------------------------- Benchmark 7

BENCHMARK_7_MONTH_UTILITIES = """
function monthKey(monthYear) {
  const [year, month] = monthYear.split('-').map(Number);
  return new Date(year, month, 1);
}

function nextMonth(monthYear) {
  const [year, month] = monthYear.split('-').map(Number);
  return new Date(year, month + 1, 1);
}

module.exports = { monthKey, nextMonth };
"""


async def test_benchmark_7_month_utilities():
    _skip_if_unavailable()
    findings = await _run(BENCHMARK_7_MONTH_UTILITIES)
    themes = _detected_themes(findings)
    assert themes & {"date_validation"}, f"expected a date-validation concern, detected {themes}"

    # negative assertion: no slicing/substring operation exists in this
    # source -- the slicing-specific KB standard should not be attached
    all_knowledge_ids = {
        std.get("rule_id")
        for f in findings
        for std in getattr(f, "knowledge_standards", [])
    }
    assert "js_date_slice_without_validation" not in all_knowledge_ids, (
        "slicing-specific guidance attached to a snippet with no slicing operation"
    )
