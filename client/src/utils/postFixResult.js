export function getAuthoritativeScore(score) {
  const value = score?.overall_score ?? score?.health_score;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function findingIdentity(finding) {
  if (!finding) return "";
  if (finding.finding_id) return `id:${finding.finding_id}`;
  const rule = finding.rule_id || finding.rule || finding.type || "";
  const file = finding.file || finding.path || "";
  const line = finding.line ?? "";
  const title = finding.title || finding.message || finding.description || "";
  return `sig:${rule}|${file}|${line}|${title}`;
}

export function compareFindings(beforeFindings = [], afterFindings = []) {
  const beforeMap = new Map(beforeFindings.map((finding) => [findingIdentity(finding), finding]).filter(([key]) => key));
  const afterMap = new Map(afterFindings.map((finding) => [findingIdentity(finding), finding]).filter(([key]) => key));

  return {
    resolved_findings: [...beforeMap].filter(([key]) => !afterMap.has(key)).map(([, finding]) => finding),
    remaining_findings: [...beforeMap].filter(([key]) => afterMap.has(key)).map(([, finding]) => finding),
    new_findings: [...afterMap].filter(([key]) => !beforeMap.has(key)).map(([, finding]) => finding),
  };
}

export function buildPostFixResult({ beforeScore, afterScore, beforeFindings, afterFindings, verificationStatus = "verified", error = "" }) {
  return {
    before_score: beforeScore,
    after_score: afterScore,
    verification_status: verificationStatus,
    error,
    ...compareFindings(beforeFindings, afterFindings),
  };
}
