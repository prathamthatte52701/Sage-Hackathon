import { useEffect, useMemo, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { AnimatePresence, motion } from "framer-motion";
import {
  analyzeProject,
  applyProjectFix,
  chatAboutProject,
  explainIssue,
  fixedProjectZipUrl,
  generatePasteFix,
  getHistory,
  importFromGithub,
  reasonFinding,
  reanalyzeProject,
  reviewCode,
  scoreProject,
  transformFinding,
  uploadProject,
} from "./api/client";
import useSessionId from "./hooks/useSessionId";
import { LANGUAGES, MAX_CHARS } from "./components/CodeEditor";
import ReanalysisResult from "./components/ReanalysisResult";
import AuthScreen from "./components/AuthScreen";
import { useAuth } from "./context/AuthContext";

const NAV = ["Overview", "Analyze", "Findings", "Ask AI", "History"];
const SEVERITIES = ["critical", "high", "medium", "low"];
const SOURCE_LIMITS = "ZIP archives up to 300MB, 2,000 files, 600MB uncompressed.";

function cx(...classes) {
  return classes.filter(Boolean).join(" ");
}

function severityTone(severity) {
  return {
    critical: "border-red-500/35 bg-red-500/12 text-red-300",
    high: "border-orange-500/35 bg-orange-500/12 text-orange-300",
    medium: "border-amber-500/35 bg-amber-500/12 text-amber-300",
    low: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
  }[severity] || "border-white/10 bg-white/5 text-[var(--sage-text-secondary)]";
}

function languageExtension(language) {
  return { javascript: "js", typescript: "ts", python: "py", java: "java", cpp: "cpp" }[language] || "txt";
}

function downloadTextFile(filename, content, type = "text/plain") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function sha256Hex(content) {
  const bytes = new TextEncoder().encode(content || "");
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function patchReasonMessage(reason) {
  return {
    target_not_found: "Manual review required: the original code is no longer present.",
    ambiguous_target: "Manual review required: the target code appears more than once.",
    stale_source: "Manual review required: the editor changed after this fix was generated.",
    overlapping_patch: "Manual review required: this fix overlaps another patch.",
    malformed_fix: "Manual review required: the generated patch is incomplete.",
  }[reason] || "Manual review required: this change could not be applied safely.";
}

function countOccurrences(content, needle) {
  if (!needle) return 0;
  let count = 0;
  let index = content.indexOf(needle);
  while (index !== -1) {
    count += 1;
    index = content.indexOf(needle, index + needle.length);
  }
  return count;
}

function spansOverlap(a, b) {
  if (!a || !b) return false;
  return !(a.end <= b.start || a.start >= b.end);
}

async function applyValidatedReplacement(content, fix, appliedSpans = []) {
  const original = fix?.original_code || fix?.original_snippet || "";
  const fixed = fix?.fixed_code || fix?.proposed_fix || "";
  if (!original || fixed === undefined || original === fixed) {
    throw new Error("malformed_fix");
  }
  if (fix?.source_hash && (await sha256Hex(content)) !== fix.source_hash) {
    throw new Error("stale_source");
  }
  const matches = countOccurrences(content, original);
  if (matches === 0) throw new Error("target_not_found");
  if (matches > 1) throw new Error("ambiguous_target");
  const start = content.indexOf(original);
  const span = { start, end: start + original.length };
  if (appliedSpans.some((applied) => spansOverlap(span, applied))) {
    throw new Error("overlapping_patch");
  }
  return {
    updated: content.slice(0, start) + fixed + content.slice(span.end),
    span,
  };
}

function hasOverlappingGeneratedPatch(key, fix, fixes) {
  if (!fix?.can_apply) return false;
  const span = { start: fix.target_start || 0, end: fix.target_end || 0 };
  if (!span.end || span.end <= span.start) return false;
  return Object.entries(fixes).some(([otherKey, otherFix]) => {
    if (otherKey === key || !otherFix?.can_apply) return false;
    const otherSpan = { start: otherFix.target_start || 0, end: otherFix.target_end || 0 };
    return otherSpan.end > otherSpan.start && spansOverlap(span, otherSpan);
  });
}

function scoreTone(score) {
  if (score >= 80) return "text-[var(--sage-success)]";
  if (score >= 60) return "text-[var(--sage-warning)]";
  return "text-[var(--sage-danger)]";
}

// The 7 canonical project-health dimensions, in the fixed order they must
// always render -- never derived from Object.entries(score.categories),
// which would silently drop a dimension if the backend omitted a key.
const HEALTH_DIMENSIONS = [
  { key: "security", label: "Security" },
  { key: "code_quality", label: "Code Quality" },
  { key: "architecture", label: "Architecture" },
  { key: "testing", label: "Testing" },
  { key: "api_design", label: "API Design" },
  { key: "performance", label: "Performance" },
  { key: "production_readiness", label: "Production Readiness" },
];

function Panel({ children, className = "" }) {
  return <section className={cx("sage-panel rounded-[12px]", className)}>{children}</section>;
}

function SeverityBadge({ severity }) {
  return (
    <span className={cx("sage-mono rounded-md border px-2 py-1 text-[11px] font-semibold uppercase", severityTone(severity))}>
      {severity || "info"}
    </span>
  );
}

function SourceBadge({ source }) {
  return (
    <span className="sage-mono rounded-md border border-[var(--sage-border-default)] bg-black/20 px-2 py-1 text-[10px] uppercase tracking-wide text-[var(--sage-text-muted)]">
      {source || "local"}
    </span>
  );
}

function getMeta(project) {
  return project?.project || {};
}

function findingCounts(findings = []) {
  return findings.reduce(
    (acc, f) => {
      const sev = f?.severity || "low";
      acc[sev] = (acc[sev] || 0) + 1;
      return acc;
    },
    { critical: 0, high: 0, medium: 0, low: 0 }
  );
}

function sortFindings(findings = []) {
  const rank = { critical: 0, high: 1, medium: 2, low: 3 };
  return [...findings].sort((a, b) => (rank[a?.severity] ?? 9) - (rank[b?.severity] ?? 9));
}

function detectSnippetLanguage(code, selectedLanguage) {
  const text = code || "";
  const checks = [
    { language: "typescript", pattern: /\b(interface|type\s+\w+\s*=|:\s*(string|number|boolean|unknown|Record<)|as\s+const)\b/, signal: "TypeScript syntax" },
    { language: "javascript", pattern: /\b(export\s+function|export\s+const|const\s+\w+\s*=|let\s+\w+\s*=|=>|console\.|module\.exports|require\s*\()/, signal: "JavaScript syntax" },
    { language: "python", pattern: /(^|\n)\s*(def\s+\w+\s*\(|import\s+\w+|from\s+\w+\s+import|print\s*\(|if\s+__name__\s*==)/, signal: "Python syntax" },
  ];
  const hit = checks.find((item) => item.pattern.test(text));
  if (!hit) return { detected: selectedLanguage, confidence: "low", mismatch: false, signal: "" };
  return {
    detected: hit.language,
    confidence: "high",
    mismatch: hit.language !== selectedLanguage,
    signal: hit.signal,
  };
}

function AppShell({ activeView, setActiveView, project, score, sourceType, children }) {
  const { user, logout } = useAuth();
  const meta = getMeta(project);
  const findings = project?.findings || [];
  const hasProject = Boolean(project);
  return (
    <div className="min-h-screen text-[var(--sage-text-primary)]">
      <aside className="fixed inset-y-0 left-0 z-40 w-[232px] border-r border-white/[0.055] bg-[#080c09] p-4">
        <div className="flex items-center gap-3 border-b border-[var(--sage-border-subtle)] pb-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg border border-[var(--sage-border-accent)] bg-[var(--sage-accent-soft)] text-sm font-black text-[var(--sage-accent)]">
            S
          </div>
          <div>
            <p className="text-lg font-bold tracking-wide">CODE MASTER AI</p>
            <p className="sage-mono text-[10px] tracking-[0.17em] text-[var(--sage-text-muted)]">AI CODE INTELLIGENCE</p>
          </div>
        </div>

        <div className="mt-5 rounded-xl border border-[var(--sage-border-subtle)] bg-black/20 p-3">
          <p className="sage-mono text-[10px] uppercase tracking-[0.18em] text-[var(--sage-text-faint)]">Workspace</p>
          <p className="mt-2 truncate text-sm font-semibold">{meta.name || "No project loaded"}</p>
          <div className="mt-2 flex items-center gap-2">
            <SourceBadge source={hasProject ? sourceType : "none"} />
            {score && <span className="sage-mono text-[11px] text-[var(--sage-text-muted)]">{score.overall_score?.toFixed?.(1)} score</span>}
          </div>
        </div>

        <nav className="mt-5 space-y-1">
          {NAV.map((item) => {
            const active = activeView === item;
            const count = item === "Findings" ? findings.length : null;
            return (
              <button
                key={item}
                type="button"
                onClick={() => setActiveView(item)}
                className={cx(
                  "relative flex h-10 w-full items-center justify-between rounded-lg px-3 text-left text-sm transition",
                  active
                    ? "bg-[var(--sage-accent-soft)] text-[var(--sage-text-primary)]"
                    : "text-[var(--sage-text-muted)] hover:bg-[var(--sage-surface-hover)] hover:text-[var(--sage-text-secondary)]"
                )}
              >
                {active && <span className="absolute left-0 top-2 h-7 w-[3px] rounded-r bg-[var(--sage-accent)]" />}
                <span>{item}</span>
                {count !== null && count > 0 && (
                  <span className="sage-mono rounded bg-black/35 px-2 py-0.5 text-[11px] text-[var(--sage-accent)]">{count}</span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="absolute bottom-4 left-4 right-4 rounded-xl bg-black/20 p-3">
          <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-accent)]">Systems operational</p>
          <p className="mt-1 truncate text-xs text-[var(--sage-text-muted)]">{user?.email || meta.name || "No active project"}</p>
          <button
            type="button"
            onClick={() => logout()}
            className="mt-2 w-full rounded-md border border-white/10 py-1 text-[11px] text-[var(--sage-text-muted)] hover:text-[var(--sage-text-secondary)]"
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="pl-[232px]">
        <div className="mx-0 max-w-[1180px] px-8 py-7">
          <header className="mb-8">
            <p className="sage-mono text-[10px] uppercase tracking-[0.2em] text-[var(--sage-text-faint)]">
              {activeView} / Live workspace
            </p>
            <div className="mt-3 flex items-center justify-between gap-4 rounded-xl bg-[#0c120e]/75 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--sage-accent-soft)] text-[var(--sage-accent)]">
                  S
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{meta.name || "Code Master AI Workspace"}</p>
                  <p className="mt-0.5 text-xs text-[var(--sage-text-muted)]">
                    {hasProject ? `${project.files?.length || 0} files tracked by Code Master AI` : "Import a project or paste code to begin."}
                  </p>
                </div>
                <SourceBadge source={hasProject ? sourceType : "workspace"} />
                <span className="sage-mono rounded-md bg-black/20 px-2 py-1 text-[10px] uppercase text-[var(--sage-text-muted)]">
                  {score ? "Analyzed" : hasProject ? "Imported" : "Ready"}
                </span>
              </div>
              <button type="button" onClick={() => setActiveView("Analyze")} className="sage-button-secondary">
                Reanalyze
              </button>
            </div>
          </header>
          {children}
        </div>
      </main>
    </div>
  );
}

function OverviewPage({ project, score, setActiveView, setQuestionSeed, setSelectedFinding }) {
  const findings = sortFindings(project?.findings || []);
  const files = project?.files || [];
  const counts = findingCounts(findings);
  const overall = score?.overall_score ?? 0;
  const topRisks = findings.slice(0, 5);
  const askPrompts = ["Top security risks", "How is the database used?", "What should I fix first?", "Is this production ready?"];

  if (!project) {
    return (
      <div className="space-y-8">
        <section className="grid items-end gap-8 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="pt-6">
            <p className="sage-mono text-[11px] uppercase tracking-[0.24em] text-[var(--sage-accent)]">AI code intelligence</p>
            <h2 className="mt-5 max-w-3xl text-5xl font-semibold leading-[1.03] tracking-tight">
              Understand risk.
              <span className="block text-[var(--sage-accent)]">Fix with evidence.</span>
            </h2>
            <p className="mt-5 max-w-2xl text-sm leading-6 text-[var(--sage-text-secondary)]">
              Import a repository to run deterministic code review, semantic project search, and knowledge-grounded reasoning in one workspace.
            </p>
            <div className="mt-7 max-w-2xl rounded-xl border border-white/[0.055] bg-black/20 p-2">
              <div className="flex flex-col gap-2 md:flex-row">
                <input className="sage-input min-h-11 flex-1 px-4 text-sm" value="Analyze this project for security and reliability risk" readOnly />
                <button type="button" onClick={() => setActiveView("Analyze")} className="sage-button-primary">
                  Import project
                </button>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {["Security audit", "Production readiness", "Evidence-backed fixes"].map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => setActiveView("Analyze")}
                  className="rounded-md border border-white/[0.055] bg-black/15 px-3 py-1.5 text-xs text-[var(--sage-text-muted)] hover:border-[var(--sage-border-accent)] hover:text-[var(--sage-text-primary)]"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
          <Panel className="p-5">
            <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Code Master AI checks</p>
            <div className="mt-5 space-y-3 text-sm text-[var(--sage-text-secondary)]">
              {["Security risks", "Reliability issues", "Code quality", "Production readiness", "Evidence-backed fixes"].map((item) => (
                <div key={item} className="flex items-center gap-3 rounded-lg bg-black/18 px-3 py-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--sage-accent)]" />
                  {item}
                </div>
              ))}
            </div>
          </Panel>
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-2xl font-medium tracking-tight">Good evening.</h2>
        <Panel className="mt-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-[var(--sage-border-accent)] bg-[var(--sage-accent-soft)] text-[var(--sage-accent)]">
                S
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-semibold">{project.project?.name || "Analyzed project"}</p>
                  <SourceBadge source={project.project?.source_type || "zip"} />
                  <span className="sage-mono rounded bg-[var(--sage-accent-soft)] px-2 py-0.5 text-[10px] uppercase text-[var(--sage-accent)]">Analyzed</span>
                </div>
                <p className="mt-1 text-xs text-[var(--sage-text-muted)]">
                  Analyzed {files.length} files with {findings.length} findings in the current workspace.
                </p>
              </div>
            </div>
            <button type="button" onClick={() => setActiveView("Analyze")} className="sage-button-secondary">
              Reanalyze
            </button>
          </div>
        </Panel>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_520px]">
        <div className="space-y-5">
          <div>
            <p className="sage-mono text-[11px] uppercase tracking-[0.24em] text-[var(--sage-accent)]">Project intelligence</p>
            <h3 className="mt-4 max-w-xl text-4xl font-semibold leading-[1.03] tracking-tight">
              Understand risk.
              <span className="block text-[var(--sage-accent)]">Fix with evidence.</span>
            </h3>
            <p className="mt-4 max-w-xl text-sm leading-6 text-[var(--sage-text-secondary)]">
              Evidence-grounded analysis across security, reliability, and code quality.
            </p>
          </div>
          <div className="rounded-xl border border-white/[0.055] bg-black/20 p-2">
            <div className="flex flex-col gap-2 md:flex-row">
              <input
                className="sage-input min-h-11 flex-1 px-4 text-sm"
                placeholder="Ask anything about this project..."
                onKeyDown={(e) => {
                  if (e.key === "Enter" && e.currentTarget.value.trim()) {
                    setQuestionSeed(e.currentTarget.value.trim());
                    setActiveView("Ask AI");
                  }
                }}
              />
              <button type="button" onClick={() => setActiveView("Ask AI")} className="sage-button-primary">
                Ask AI
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {askPrompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => {
                  setQuestionSeed(prompt);
                  setActiveView("Ask AI");
                }}
                className="rounded-md border border-white/[0.055] bg-black/15 px-3 py-1.5 text-xs text-[var(--sage-text-muted)] hover:border-[var(--sage-border-accent)] hover:text-[var(--sage-text-primary)]"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <DashboardMetric
            label="Project health"
            value={score ? overall.toFixed(1) : "--"}
            detail={score ? `${score.dimensions_evaluated ?? 0}/${score.dimensions_total ?? 7} dimensions assessed` : "/100"}
            tone={scoreTone(overall)}
          />
          <DashboardMetric label="Findings" value={findings.length} detail="Total issues" />
          <DashboardMetric label="Critical / High" value={(counts.critical || 0) + (counts.high || 0)} detail="Require attention" tone="text-[var(--sage-danger)]" />
          <DashboardMetric label="Files analyzed" value={files.length} detail="Total files" />
          <DashboardMetric label="Last analysis" value={score ? "Now" : "Pending"} detail="Current session" className="col-span-2" />
        </div>
      </section>

      {score && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <p className="sage-mono text-[11px] uppercase tracking-[0.24em] text-[var(--sage-text-muted)]">Project health</p>
            <span className="text-xs text-[var(--sage-text-muted)]">
              {score.dimensions_evaluated ?? 0}/{score.dimensions_total ?? 7} dimensions assessed
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {HEALTH_DIMENSIONS.map((dim) => (
              <HealthDimensionCard key={dim.key} label={dim.label} data={score.categories?.[dim.key]} />
            ))}
          </div>
        </section>
      )}

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr_260px]">
        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Top risks</p>
            </div>
            <button type="button" onClick={() => setActiveView("Findings")} className="sage-button-secondary">
              Open findings
            </button>
          </div>
          <div className="divide-y divide-white/[0.06]">
            {topRisks.map((finding, index) => (
              <button
                key={`${finding.file}-${finding.rule}-${index}`}
                type="button"
                onClick={() => {
                  setSelectedFinding((project.findings || []).indexOf(finding));
                  setActiveView("Findings");
                }}
                className="flex w-full items-center gap-4 py-3 text-left hover:bg-white/[0.02]"
              >
                <SeverityBadge severity={finding.severity} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{finding.message}</p>
                  <p className="sage-mono mt-1 truncate text-xs text-[var(--sage-text-muted)]">
                    {finding.file}:{finding.line || "?"} - {finding.rule}
                  </p>
                </div>
                <span className="text-[var(--sage-text-faint)]">&gt;</span>
              </button>
            ))}
            {topRisks.length === 0 && <p className="py-4 text-sm text-[var(--sage-text-muted)]">No findings detected in the current analysis.</p>}
          </div>
        </Panel>
        <Panel className="p-5">
          <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Recent activity</p>
          <div className="mt-4 space-y-3 text-sm">
            <ActivityRow label="Analysis completed" detail={`${findings.length} findings detected`} />
            {score && <ActivityRow label="Project score calculated" detail={`${overall.toFixed(1)} overall health`} />}
            <ActivityRow label="Project imported" detail={`${files.length} files discovered`} />
          </div>
          <button type="button" onClick={() => setActiveView("History")} className="mt-4 text-xs font-semibold text-[var(--sage-accent)]">
            View full history &gt;
          </button>
        </Panel>
        <Panel className="relative min-h-[230px] overflow-hidden p-5">
          <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Code Master AI signal</p>
          <div className="relative mx-auto mt-8 grid h-28 w-28 place-items-center">
            <div className="absolute inset-0 rounded-full border border-[var(--sage-border-accent)]" />
            <div className="absolute -inset-5 rounded-full border border-dashed border-white/[0.08]" />
            <div className="absolute -inset-2 rotate-45 rounded-full border border-[var(--sage-border-accent)]/70" />
            <div className="grid h-12 w-12 place-items-center rounded-full bg-[var(--sage-accent)] text-lg font-black text-[#071007]">S</div>
          </div>
          <div className="mt-8 space-y-2">
            <SignalRow label="Systems" value="Online" tone="text-[var(--sage-accent)]" />
            <SignalRow label="Evidence" value={files.length} />
          </div>
        </Panel>
      </section>
    </div>
  );
}

function HealthDimensionCard({ label, data }) {
  const [expanded, setExpanded] = useState(false);
  const status = data?.status || "not_evaluated";
  const score = typeof data?.score === "number" ? data.score : null;
  const findingCount = data?.finding_count ?? 0;
  const deductions = data?.deductions ?? [];

  const state = status === "not_evaluated" ? "not_assessed" : score >= 80 ? "healthy" : score >= 60 ? "attention" : "risk";
  const dotTone = {
    healthy: "bg-[var(--sage-success)]",
    attention: "bg-[var(--sage-warning)]",
    risk: "bg-[var(--sage-danger)]",
    not_assessed: "bg-[var(--sage-text-faint)]",
  }[state];
  const textTone = {
    healthy: "text-[var(--sage-success)]",
    attention: "text-[var(--sage-warning)]",
    risk: "text-[var(--sage-danger)]",
    not_assessed: "text-[var(--sage-text-muted)]",
  }[state];
  const stateLabel = { healthy: "Healthy", attention: "Needs attention", risk: "High risk", not_assessed: "Not assessed" }[state];
  const canExpand = deductions.length > 0;

  return (
    <button
      type="button"
      onClick={() => canExpand && setExpanded((v) => !v)}
      className={cx(
        "sage-panel w-full rounded-[12px] p-4 text-left transition-colors",
        canExpand ? "cursor-pointer hover:border-[var(--sage-border-accent)]" : "cursor-default"
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cx("h-1.5 w-1.5 shrink-0 rounded-full", dotTone)} />
        <p className="truncate text-sm font-medium text-[var(--sage-text-primary)]">{label}</p>
        {status === "partial" && (
          <span className="sage-mono ml-auto shrink-0 rounded border border-[var(--sage-border-default)] px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-[var(--sage-text-muted)]">
            Partial
          </span>
        )}
      </div>
      <div className={cx("mt-2 text-2xl font-semibold tabular-nums", textTone)}>
        {score === null ? "—" : score}
        <span className="ml-1 text-xs font-normal text-[var(--sage-text-muted)]">/ 100</span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-black/30">
        <div className={cx("h-full rounded-full", dotTone)} style={{ width: score === null ? "0%" : `${score}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-[var(--sage-text-muted)]">
          {findingCount} finding{findingCount === 1 ? "" : "s"}
        </span>
        <span className={textTone}>{stateLabel}</span>
      </div>
      {expanded && (
        <div className="mt-3 space-y-1.5 border-t border-[var(--sage-border-subtle)] pt-2.5">
          {deductions.slice(0, 2).map((d, i) => (
            <p key={i} className="text-[11px] leading-4 text-[var(--sage-text-secondary)]">
              {d.severity && <span className="sage-mono uppercase text-[var(--sage-text-muted)]">{d.severity} </span>}
              {d.reason}
              {typeof d.amount === "number" && <span className="text-[var(--sage-danger)]"> -{d.amount}</span>}
            </p>
          ))}
        </div>
      )}
    </button>
  );
}

function DashboardMetric({ label, value, detail, tone, className = "" }) {
  return (
    <Panel className={cx("p-4", className)}>
      <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">{label}</p>
      <div className={cx("mt-3 text-3xl font-semibold tabular-nums", tone || "text-[var(--sage-text-primary)]")}>{value}</div>
      <p className="mt-1 text-xs text-[var(--sage-text-muted)]">{detail}</p>
    </Panel>
  );
}

function SignalRow({ label, value, tone }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-black/35 px-3 py-2">
      <span className="sage-mono text-[10px] uppercase tracking-[0.15em] text-[var(--sage-text-muted)]">{label}</span>
      <span className={cx("sage-mono text-sm font-semibold tabular-nums", tone || "text-[var(--sage-text-primary)]")}>{value}</span>
    </div>
  );
}

function ActivityRow({ label, detail }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3">
      <span className="mt-1 h-2 w-2 rounded-full bg-[var(--sage-accent)]" />
      <div>
        <p className="font-medium">{label}</p>
        <p className="mt-1 text-xs text-[var(--sage-text-muted)]">{detail}</p>
      </div>
    </div>
  );
}

function AnalyzePage({
  code,
  setCode,
  language,
  setLanguage,
  sessionId,
  reviewResult,
  setReviewResult,
  setProjectBundle,
  setActiveView,
}) {
  const [mode, setMode] = useState("import");
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [languageNotice, setLanguageNotice] = useState("");
  const fileRef = useRef(null);
  const overLimit = code.length > MAX_CHARS;
  const detectedLanguage = useMemo(() => detectSnippetLanguage(code, language), [code, language]);

  async function runProjectFlow(uploadData, source) {
    const id = uploadData.project_id;
    setStage("Reviewing project evidence...");
    const analyzed = await analyzeProject(id);
    setStage("Calculating project score...");
    const scored = await scoreProject(id);
    setProjectBundle({ id, project: analyzed, score: scored, sourceType: source });
    setActiveView("Overview");
  }

  async function handleZip(file) {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      setStage("Reading repository...");
      const data = await uploadProject(file, sessionId);
      await runProjectFlow(data, "ZIP");
    } catch (err) {
      setError(err.message || "Upload failed.");
    } finally {
      setLoading(false);
      setStage("");
    }
  }

  async function handleGithub(e) {
    e.preventDefault();
    if (!githubUrl.trim()) return;
    setLoading(true);
    setError("");
    try {
      setStage("Importing repository...");
      const data = await importFromGithub(githubUrl.trim(), sessionId);
      await runProjectFlow(data, "GitHub");
    } catch (err) {
      setError(err.message || "Import failed.");
    } finally {
      setLoading(false);
      setStage("");
    }
  }

  async function handleReview() {
    if (!code.trim() || overLimit) return;
    setLoading(true);
    setError("");
    try {
      let reviewLanguage = language;
      if (detectedLanguage.mismatch && detectedLanguage.confidence === "high") {
        reviewLanguage = detectedLanguage.detected;
        setLanguage(reviewLanguage);
        setLanguageNotice(`Detected ${reviewLanguage} from ${detectedLanguage.signal}; reviewing with ${reviewLanguage}.`);
      } else {
        setLanguageNotice("");
      }
      setStage("Reviewing code evidence...");
      const data = await reviewCode(code, reviewLanguage, sessionId);
      setReviewResult(data);
    } catch (err) {
      setError(err.message || "Review failed.");
    } finally {
      setLoading(false);
      setStage("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Analyze codebase" title="Paste code or import a repository." subtitle="Evidence-grounded review using deterministic analysis, project retrieval, and Code Master AI reasoning." />

      <div className="flex w-fit rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-1">
        {["import", "paste"].map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setMode(tab)}
            className={cx(
              "rounded-md px-4 py-2 text-sm font-semibold capitalize transition",
              mode === tab ? "bg-[var(--sage-accent-soft)] text-[var(--sage-accent)]" : "text-[var(--sage-text-muted)] hover:text-[var(--sage-text-primary)]"
            )}
          >
            {tab === "import" ? "Import Project" : "Paste Code"}
          </button>
        ))}
      </div>

      {error && <ErrorState message={error} />}
      {loading && <LoadingState label={stage || "Analyzing repository..."} />}

      {mode === "paste" ? (
        <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--sage-border-subtle)] p-4">
              <div>
                <select value={language} onChange={(e) => setLanguage(e.target.value)} className="sage-input px-3 py-2 text-sm">
                  {LANGUAGES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                {(languageNotice || detectedLanguage.mismatch) && (
                  <p className="mt-2 max-w-xl text-xs text-[var(--sage-warning)]">
                    {languageNotice || `This looks like ${detectedLanguage.detected}; selected language is ${language}. Code Master AI will switch before review.`}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className={cx("sage-mono text-xs", overLimit ? "text-red-300" : "text-[var(--sage-text-muted)]")}>
                  {code.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
                </span>
                <button type="button" onClick={handleReview} disabled={loading || !code.trim() || overLimit} className="sage-button-primary disabled:opacity-50">
                  Review code
                </button>
              </div>
            </div>
            <Editor
              height="520px"
              language={language}
              value={code}
              onChange={(value) => setCode(value || "")}
              theme="vs-dark"
              options={{ minimap: { enabled: false }, fontSize: 14, scrollBeyondLastLine: false, automaticLayout: true }}
            />
          </Panel>
          <ReviewKnowledgePanel result={reviewResult} />
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
          <Panel className="p-6">
            <input ref={fileRef} type="file" accept=".zip" className="hidden" onChange={(e) => handleZip(e.target.files?.[0])} />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={loading}
              className="flex min-h-[220px] w-full flex-col items-center justify-center rounded-xl border border-dashed border-[var(--sage-border-accent)] bg-[var(--sage-accent-soft)] p-8 text-center transition hover:bg-[rgba(166,255,91,0.14)] disabled:opacity-60"
            >
              <span className="sage-mono text-[11px] uppercase tracking-[0.2em] text-[var(--sage-accent)]">ZIP import</span>
              <span className="mt-3 text-xl font-semibold">Drop or select a repository archive</span>
              <span className="mt-2 max-w-md text-sm text-[var(--sage-text-secondary)]">{SOURCE_LIMITS}</span>
            </button>
            <form onSubmit={handleGithub} className="mt-5 flex flex-col gap-3 md:flex-row">
              <input value={githubUrl} onChange={(e) => setGithubUrl(e.target.value)} className="sage-input min-h-10 flex-1 px-3 text-sm" placeholder="owner/repo or https://github.com/owner/repo" />
              <button type="submit" disabled={loading || !githubUrl.trim()} className="sage-button-secondary disabled:opacity-50">
                Import GitHub
              </button>
            </form>
          </Panel>
          <Panel className="p-5">
            <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Supported workflow</p>
            <div className="mt-4 space-y-3 text-sm text-[var(--sage-text-secondary)]">
              <ActivityRow label="Read repository" detail="Normalize files and dependency manifests." />
              <ActivityRow label="Run deterministic analysis" detail="Find concrete evidence and rules." />
              <ActivityRow label="Score project" detail="Calculate category and overall health." />
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}

function PageHeader({ eyebrow, title, subtitle }) {
  return (
    <div>
      <p className="sage-mono text-[11px] uppercase tracking-[0.2em] text-[var(--sage-accent)]">{eyebrow}</p>
      <h2 className="mt-2 text-3xl font-semibold tracking-tight">{title}</h2>
      {subtitle && <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--sage-text-secondary)]">{subtitle}</p>}
    </div>
  );
}

function LoadingState({ label }) {
  return (
    <Panel className="p-4">
      <div className="flex items-center gap-3 text-sm text-[var(--sage-text-secondary)]">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--sage-border-default)] border-t-[var(--sage-accent)]" />
        {label}
      </div>
    </Panel>
  );
}

function ErrorState({ message }) {
  return <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{message}</div>;
}

function FindingsPage({ project, selectedFinding, setSelectedFinding }) {
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("all");
  const findings = useMemo(() => project?.findings || [], [project]);
  const filtered = useMemo(() => {
    return sortFindings(findings).filter((f) => {
      if (severity !== "all" && f.severity !== severity) return false;
      const text = `${f.message} ${f.file} ${f.rule}`.toLowerCase();
      return text.includes(query.toLowerCase());
    });
  }, [findings, query, severity]);
  const active = findings[selectedFinding] || filtered[0];
  const activeIndex = findings.indexOf(active);

  if (!project) {
    return <EmptyState title="No analyzed project yet." action="Analyze your first project" />;
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Findings" title={`${findings.length} issues detected across ${project.files?.length || 0} files.`} subtitle="Select a finding to inspect evidence, explanation, generated fix, and reanalysis." />
      <div className="grid gap-6 xl:grid-cols-[minmax(360px,0.8fr)_1.2fr]">
        <Panel className="overflow-hidden">
          <div className="border-b border-[var(--sage-border-subtle)] p-4">
            <input value={query} onChange={(e) => setQuery(e.target.value)} className="sage-input min-h-10 w-full px-3 text-sm" placeholder="Search findings..." />
            <div className="mt-3 flex flex-wrap gap-2">
              {["all", ...SEVERITIES].map((sev) => (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setSeverity(sev)}
                  className={cx(
                    "rounded-md border px-3 py-1.5 text-xs capitalize",
                    severity === sev ? "border-[var(--sage-border-accent)] bg-[var(--sage-accent-soft)] text-[var(--sage-accent)]" : "border-[var(--sage-border-subtle)] bg-black/20 text-[var(--sage-text-muted)]"
                  )}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>
          <div className="max-h-[calc(100vh-250px)] overflow-y-auto">
            {filtered.map((finding) => {
              const index = findings.indexOf(finding);
              return (
                <button
                  key={`${finding.file}-${finding.rule}-${index}`}
                  type="button"
                  onClick={() => setSelectedFinding(index)}
                  className={cx("w-full border-b border-white/[0.06] p-4 text-left transition hover:bg-white/[0.025]", index === activeIndex && "bg-[var(--sage-accent-soft)]")}
                >
                  <div className="flex items-center justify-between gap-3">
                    <SeverityBadge severity={finding.severity} />
                    <span className="sage-mono text-[11px] text-[var(--sage-text-muted)]">{finding.rule}</span>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm font-medium">{finding.message}</p>
                  <p className="sage-mono mt-2 truncate text-xs text-[var(--sage-text-muted)]">{finding.file}:{finding.line || "?"}</p>
                </button>
              );
            })}
          </div>
        </Panel>
        <FindingDetail project={project} finding={active} findingIndex={activeIndex} />
      </div>
    </div>
  );
}

function FindingDetail({ project, finding, findingIndex }) {
  const [reason, setReason] = useState(finding?.reasoning || null);
  const [fix, setFix] = useState(finding?.transform || null);
  const [reanalysis, setReanalysis] = useState(null);
  const [applyResult, setApplyResult] = useState(null);
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setReason(finding?.reasoning || null);
    setFix(finding?.transform || null);
    setReanalysis(null);
    setApplyResult(null);
    setError("");
  }, [finding]);

  if (!finding) {
    return <EmptyState title="No finding selected." action="Choose a finding from the list." />;
  }

  const file = (project.files || []).find((f) => f.path === finding.file);

  async function explain() {
    setLoading("explain");
    setError("");
    try {
      const data = project?._id ? await reasonFinding(project._id, findingIndex) : null;
      setReason(data);
    } catch (err) {
      setError(err.message || "Could not explain this finding.");
    } finally {
      setLoading("");
    }
  }

  async function generate() {
    setLoading("fix");
    setError("");
    try {
      const data = await transformFinding(project._id, findingIndex);
      setFix(data);
    } catch (err) {
      setError(err.message || "Could not generate a fix.");
    } finally {
      setLoading("");
    }
  }

  async function reanalyze() {
    setLoading("reanalyze");
    setError("");
    try {
      const data = await reanalyzeProject(project._id, findingIndex);
      setReanalysis(data);
    } catch (err) {
      setError(err.message || "Could not reanalyze.");
    } finally {
      setLoading("");
    }
  }

  async function applyFix() {
    setLoading("apply");
    setError("");
    try {
      const data = await applyProjectFix(project._id, findingIndex);
      setApplyResult(data);
    } catch (err) {
      setError(err.message || "Could not apply this fix safely.");
    } finally {
      setLoading("");
    }
  }

  function downloadFixedZip() {
    window.location.href = fixedProjectZipUrl(project._id);
  }

  return (
    <Panel className="overflow-hidden">
      <div className="border-b border-[var(--sage-border-subtle)] p-5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <span className="sage-mono rounded-md border border-[var(--sage-border-subtle)] bg-black/20 px-2 py-1 text-[11px] text-[var(--sage-text-muted)]">{finding.rule}</span>
        </div>
        <h3 className="mt-4 text-xl font-semibold">{finding.message}</h3>
        <p className="sage-mono mt-2 text-xs text-[var(--sage-text-muted)]">{finding.file}:{finding.line || "?"}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={explain} disabled={loading === "explain"} className="sage-button-secondary">Explain</button>
          <button type="button" onClick={generate} disabled={loading === "fix"} className="sage-button-primary">Generate fix</button>
          <button type="button" onClick={applyFix} disabled={!fix?.can_apply || loading === "apply"} className="sage-button-secondary disabled:opacity-50">{applyResult ? "Applied" : "Apply Fix"}</button>
          <button type="button" onClick={reanalyze} disabled={!fix || loading === "reanalyze"} className="sage-button-secondary disabled:opacity-50">Reanalyze</button>
          <button type="button" onClick={downloadFixedZip} disabled={!applyResult} className="sage-button-secondary disabled:opacity-50">Download Fixed ZIP</button>
        </div>
      </div>
      <div className="space-y-5 p-5">
        {error && <ErrorState message={error} />}
        {loading && <LoadingState label={loading === "reanalyze" ? "Reanalyzing with proposed fix..." : "Reviewing project evidence..."} />}
        {applyResult && (
          <TrustSection label="Fix state">
            <div className="space-y-2 text-sm text-[var(--sage-text-secondary)]">
              <p><span className="font-semibold text-[var(--sage-text-primary)]">Fix applied:</span> {applyResult.file}</p>
              <p>{applyResult.verification}</p>
              {applyResult.modified_files?.length > 0 && <p>{applyResult.modified_files.length} file(s) modified: {applyResult.modified_files.join(", ")}</p>}
            </div>
          </TrustSection>
        )}
        <TrustSection label="Project evidence">
          <CodeViewer file={file} evidence={finding.evidence} line={finding.line} />
        </TrustSection>
        <TrustSection label="AI explanation">
          {reason ? (
            <div className="space-y-3 text-sm leading-6 text-[var(--sage-text-secondary)]">
              <p>{reason.reasoning || "No reasoning returned."}</p>
              {reason.impact && <p><span className="font-semibold text-[var(--sage-text-primary)]">Impact:</span> {reason.impact}</p>}
              {reason.recommendation && <p><span className="font-semibold text-[var(--sage-text-primary)]">Recommendation:</span> {reason.recommendation}</p>}
            </div>
          ) : (
            <p className="text-sm text-[var(--sage-text-muted)]">Generate an explanation to confirm this finding in context.</p>
          )}
        </TrustSection>
        <TrustSection label="Suggested fix">
          {fix ? (
            <FixPanel fix={fix} />
          ) : (
            <p className="text-sm text-[var(--sage-text-muted)]">Generate a focused code change for this finding.</p>
          )}
        </TrustSection>
        {reanalysis && <TrustSection label="Reanalysis result"><ReanalysisResult result={reanalysis} /></TrustSection>}
      </div>
    </Panel>
  );
}

function TrustSection({ label, children }) {
  return (
    <section>
      <p className="sage-mono mb-3 text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">{label}</p>
      <div className="rounded-xl border border-[var(--sage-border-subtle)] bg-black/20 p-4">{children}</div>
    </section>
  );
}

function CodeViewer({ file, evidence, line }) {
  const lines = (file?.content || evidence || "No source content available.").split("\n");
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--sage-border-subtle)] bg-[#050705]">
      <div className="flex items-center justify-between border-b border-[var(--sage-border-subtle)] px-3 py-2">
        <span className="sage-mono truncate text-xs text-[var(--sage-text-secondary)]">{file?.path || "evidence snippet"}</span>
        {line && <span className="sage-mono text-[11px] text-[var(--sage-text-muted)]">line {line}</span>}
      </div>
      <pre className="max-h-80 overflow-auto p-3 text-xs leading-6">
        {lines.map((content, i) => {
          const no = i + 1;
          const active = line && Math.abs(no - line) <= 1;
          return (
            <div key={no} className={cx("grid grid-cols-[42px_1fr] gap-3 rounded px-2", active && "bg-[var(--sage-accent-soft)]")}>
              <span className="sage-mono text-right text-[var(--sage-text-faint)]">{no}</span>
              <code className="sage-mono whitespace-pre-wrap text-[var(--sage-text-secondary)]">{content || " "}</code>
            </div>
          );
        })}
      </pre>
    </div>
  );
}

function AskAiPage({ project, questionSeed, setQuestionSeed }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const seedHandled = useRef("");

  useEffect(() => {
    if (questionSeed && questionSeed !== seedHandled.current) {
      setQuestion(questionSeed);
      seedHandled.current = questionSeed;
      setQuestionSeed("");
    }
  }, [questionSeed, setQuestionSeed]);

  async function ask(q = question) {
    const text = q.trim();
    if (!text || !project?._id) return;
    setQuestion("");
    setLoading(true);
    try {
      const data = await chatAboutProject(project._id, text);
      setMessages((items) => [...items, { question: text, ...data }]);
    } catch (err) {
      setMessages((items) => [...items, { question: text, error: err.message || "Could not answer." }]);
    } finally {
      setLoading(false);
    }
  }

  if (!project) return <EmptyState title="Ask AI about your codebase." action="Import a project first." />;

  const suggested = ["Is this project production ready?", "What are the top security risks?", "How is the database used?", "What should I fix first?", "Which files contain the riskiest code?"];
  const cited = [...new Set(messages.flatMap((m) => m.cited_files || []))];

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <Panel className="flex min-h-[calc(100vh-150px)] flex-col overflow-hidden">
        <div className="border-b border-[var(--sage-border-subtle)] p-5">
          <PageHeader eyebrow="Ask AI" title="Code intelligence console" subtitle="Ask grounded questions about project evidence, cited files, and engineering guidance." />
        </div>
        <div className="flex-1 space-y-4 overflow-auto p-5">
          {messages.length === 0 && (
            <div className="rounded-xl border border-[var(--sage-border-subtle)] bg-black/20 p-6">
              <h3 className="text-xl font-semibold">Ask AI about your codebase</h3>
              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {suggested.map((item) => (
                  <button key={item} type="button" onClick={() => ask(item)} className="rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3 text-left text-sm text-[var(--sage-text-secondary)] hover:border-[var(--sage-border-accent)] hover:text-[var(--sage-text-primary)]">
                    {item}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <ChatMessage key={`${message.question}-${index}`} message={message} />
          ))}
          {loading && <LoadingState label="Reviewing project evidence and relevant standards..." />}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask();
          }}
          className="flex gap-3 border-t border-[var(--sage-border-subtle)] p-4"
        >
          <input value={question} onChange={(e) => setQuestion(e.target.value)} className="sage-input min-h-11 flex-1 px-4 text-sm" placeholder="Ask anything about this project..." />
          <button type="submit" disabled={loading || !question.trim()} className="sage-button-primary disabled:opacity-50">Ask</button>
        </form>
      </Panel>
      <Panel className="h-fit p-5">
        <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Evidence panel</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {cited.length === 0 ? (
            <p className="text-sm text-[var(--sage-text-muted)]">Cited project files appear here after Code Master AI answers.</p>
          ) : (
            cited.map((file) => <CitationChip key={file} file={file} />)
          )}
        </div>
      </Panel>
    </div>
  );
}

function ChatMessage({ message }) {
  return (
    <article className="rounded-xl border border-[var(--sage-border-subtle)] bg-black/20 p-4">
      <p className="text-sm font-semibold">{message.question}</p>
      {message.error ? (
        <p className="mt-3 text-sm text-red-300">{message.error}</p>
      ) : (
        <div className="mt-4 space-y-4">
          <section>
            <p className="sage-mono mb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Answer</p>
            <p className="whitespace-pre-wrap text-sm leading-6 text-[var(--sage-text-secondary)]">{message.answer}</p>
          </section>
          {(message.cited_files || []).length > 0 && (
            <section>
              <p className="sage-mono mb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Cited files</p>
              <div className="flex flex-wrap gap-2">{message.cited_files.map((file) => <CitationChip key={file} file={file} />)}</div>
            </section>
          )}
        </div>
      )}
    </article>
  );
}

function CitationChip({ file }) {
  return <span className="sage-mono rounded-md border border-[var(--sage-border-subtle)] bg-black/30 px-2 py-1 text-xs text-[var(--sage-text-secondary)]">{file}</span>;
}

function historyReviewSummary(item) {
  const issues = item?.issues || [];
  if (!issues.length) return "Review complete · no issues found";
  const counts = issues.reduce((acc, issue) => {
    const key = issue?.severity || "low";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const severityLine = ["critical", "high", "medium", "low"]
    .filter((key) => counts[key])
    .map((key) => `${counts[key]} ${key[0].toUpperCase()}${key.slice(1)}`)
    .join(" · ");
  return `Review complete · ${issues.length} issue${issues.length === 1 ? "" : "s"} found${severityLine ? ` · ${severityLine}` : ""}`;
}

function HistoryPage({ sessionId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    getHistory(sessionId)
      .then((data) => setItems(Array.isArray(data) ? data : []))
      .catch((err) => setError(err.message || "Could not load history."))
      .finally(() => setLoading(false));
  }, [sessionId]);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="History" title="Session review history" subtitle="Past paste-code reviews from this Code Master AI session." />
      {loading && <LoadingState label="Loading history..." />}
      {error && <ErrorState message={error} />}
      {!loading && !error && items.length === 0 && <EmptyState title="No analyzed code snippets yet." action="Analyze your first project or paste code." />}
      <div className="space-y-3">
        {items.map((item) => (
          <Panel key={item._id} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="sage-mono text-[11px] uppercase text-[var(--sage-text-muted)]">{item.language}</p>
                <p className="mt-2 line-clamp-2 text-sm text-[var(--sage-text-secondary)]">{historyReviewSummary(item)}</p>
              </div>
              <span className="sage-mono text-xs text-[var(--sage-text-muted)]">{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</span>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ title, action }) {
  return (
    <Panel className="p-8 text-center">
      <h3 className="text-xl font-semibold">{title}</h3>
      <p className="mt-2 text-sm text-[var(--sage-text-muted)]">{action}</p>
    </Panel>
  );
}

function ReviewKnowledgePanel({ result }) {
  return (
    <Panel className="p-5">
      <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">Code Master AI knowledge</p>
      {!result ? (
        <div className="mt-4 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3">
          <p className="text-sm font-medium">Relevant engineering standards are retrieved automatically during review.</p>
          <p className="mt-2 text-xs leading-5 text-[var(--sage-text-muted)]">
            Guidance appears inside each finding when Code Master AI has supporting standards.
          </p>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3">
          <p className="text-sm font-medium">Relevant guidance is attached to each finding.</p>
          <p className="mt-2 text-xs leading-5 text-[var(--sage-text-muted)]">
            Knowledge is used as engineering guidance, not proof of a defect.
          </p>
        </div>
      )}
    </Panel>
  );
}

function PasteReviewResults({ result, code, setCode, language, sessionId, setReviewResult }) {
  const [originalSource] = useState(code);
  const [fixes, setFixes] = useState({});
  const [states, setStates] = useState({});
  const [appliedSpans, setAppliedSpans] = useState([]);
  const [explanations, setExplanations] = useState({});
  const [loadingFix, setLoadingFix] = useState("");
  const [loadingExplain, setLoadingExplain] = useState("");
  const [actionError, setActionError] = useState("");
  if (!result) return null;
  const hasAppliedPatches = appliedSpans.length > 0;
  const sourceChangedSinceReview = code !== originalSource;
  const deterministic = result.deterministic_findings || result.issues || [];
  const aiQuality = result.ai_quality_review || [];
  const allIssues = [
    ...deterministic.map((issue) => ({ ...issue, source: "deterministic" })),
    ...aiQuality.map((issue) => ({ ...issue, source: "ai_quality" })),
  ];
  const counts = allIssues.reduce((acc, issue) => {
    const key = issue.severity || "info";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const countLine = SEVERITIES
    .filter((key) => counts[key])
    .map((key) => `${counts[key]} ${key[0].toUpperCase()}${key.slice(1)}`)
    .join(" · ");

  async function generateFix(issue, key) {
    setLoadingFix(key);
    setActionError("");
    try {
      const fix = await generatePasteFix(code, language, issue);
      setFixes((items) => ({ ...items, [key]: fix }));
      setStates((items) => ({ ...items, [key]: fix.can_apply ? "Generated" : "Manual review required" }));
    } catch (err) {
      setActionError(err.message || "Could not generate a fix.");
    } finally {
      setLoadingFix("");
    }
  }

  async function explainFinding(issue, key) {
    setLoadingExplain(key);
    setActionError("");
    try {
      const data = await explainIssue(issue, code, language);
      setExplanations((items) => ({ ...items, [key]: data.explanation || "No explanation returned." }));
    } catch (err) {
      setActionError(err.message || "Could not explain this finding.");
    } finally {
      setLoadingExplain("");
    }
  }

  async function applyFix(key) {
    const fix = fixes[key];
    try {
      if (hasOverlappingGeneratedPatch(key, fix, fixes)) {
        throw new Error("overlapping_patch");
      }
      const { updated, span } = await applyValidatedReplacement(code, fix, appliedSpans);
      setCode(updated);
      setAppliedSpans((items) => [...items, span]);
      setStates((items) => ({ ...items, [key]: "Fix applied" }));
    } catch (err) {
      const reason = err.message || "malformed_fix";
      setStates((items) => ({ ...items, [key]: "Manual review required" }));
      setFixes((items) => ({
        ...items,
        [key]: { ...items[key], can_apply: false, apply_failure_reason: reason },
      }));
      setActionError(patchReasonMessage(reason));
    }
  }

  async function reanalyzePaste() {
    setActionError("");
    try {
      const data = await reviewCode(code, language, sessionId);
      setReviewResult(data);
    } catch (err) {
      setActionError(err.message || "Could not reanalyze updated code.");
    }
  }

  function downloadFixed() {
    downloadTextFile(`fixed-code.${languageExtension(language)}`, code);
  }

  function downloadPatch() {
    const diff = Object.values(fixes).map((fix) => fix.diff).filter(Boolean).join("\n");
    if (diff) downloadTextFile("fixed-code.patch", diff, "text/x-diff");
  }

  return (
    <div className="space-y-4">
      <Panel className="p-5">
        <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-accent)]">Review complete</p>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h3 className="text-2xl font-semibold">{allIssues.length} issue{allIssues.length === 1 ? "" : "s"} found</h3>
            {countLine && <p className="mt-2 text-sm text-[var(--sage-text-secondary)]">{countLine}</p>}
            <p className="mt-2 text-xs text-[var(--sage-text-muted)]">Evidence-grounded code quality review completed.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={reanalyzePaste} className="sage-button-secondary">Reanalyze</button>
            <button type="button" onClick={downloadFixed} disabled={!hasAppliedPatches} className="sage-button-primary disabled:opacity-50">Download Fixed File</button>
            <button type="button" onClick={downloadPatch} disabled={!Object.values(fixes).some((fix) => fix.diff)} className="sage-button-secondary disabled:opacity-50">Download Patch</button>
          </div>
        </div>
        {!hasAppliedPatches && (
          <p className="mt-3 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3 text-xs text-[var(--sage-text-muted)]">
            Generated fixes are previews only. Apply a fix to update the editor and enable fixed-file download.
          </p>
        )}
        {sourceChangedSinceReview && (
          <p className="mt-3 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3 text-xs text-[var(--sage-accent)]">
            Working source has applied edits. Reanalyze checks the current editor content only.
          </p>
        )}
        {result.language_detection?.mismatch && (
          <p className="mt-3 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3 text-xs text-[var(--sage-warning)]">
            Language switched from {result.language_detection.selected} to {result.language_detection.effective} based on detected syntax.
          </p>
        )}
        {actionError && <div className="mt-3"><ErrorState message={actionError} /></div>}
      </Panel>

      <ReviewSection
        title="Review findings"
        empty="No evidence-backed concerns were found."
        issues={allIssues}
        fixes={fixes}
        states={states}
        explanations={explanations}
        loadingFix={loadingFix}
        loadingExplain={loadingExplain}
        onGenerateFix={generateFix}
        onExplain={explainFinding}
        onApplyFix={applyFix}
      />
    </div>
  );
}

const FINDINGS_PAGE_SIZE = 5;

function defaultSeverityFor(counts) {
  return SEVERITIES.find((sev) => counts[sev] > 0) || null;
}

function ReviewSection({
  title,
  empty,
  issues,
  fixes = {},
  states = {},
  explanations = {},
  loadingFix = "",
  loadingExplain = "",
  onGenerateFix,
  onExplain,
  onApplyFix,
}) {
  const counts = useMemo(() => findingCounts(issues), [issues]);
  const [activeSeverity, setActiveSeverity] = useState(() => defaultSeverityFor(counts));
  const [page, setPage] = useState(1);

  // Findings can shrink in place (Apply Fix + Reanalyze) without this
  // section remounting -- if the selected severity ran out, fall back to
  // the highest remaining one instead of showing an empty tab.
  useEffect(() => {
    if (activeSeverity && counts[activeSeverity] > 0) return;
    setActiveSeverity(defaultSeverityFor(counts));
    setPage(1);
  }, [counts, activeSeverity]);

  function selectSeverity(severity) {
    setActiveSeverity(severity);
    setPage(1);
  }

  // Carry each issue's original index (used to key fixes/states/explanations,
  // set by the caller before filtering) through the severity/page split so
  // Generate Fix / Apply Fix keep operating on the correct finding.
  const indexed = useMemo(() => issues.map((issue, index) => ({ issue, index })), [issues]);
  const visible = useMemo(
    () => indexed.filter(({ issue }) => (issue.severity || "low") === activeSeverity),
    [indexed, activeSeverity]
  );
  const totalPages = Math.max(1, Math.ceil(visible.length / FINDINGS_PAGE_SIZE));
  const page_ = Math.min(page, totalPages);
  const pageItems = visible.slice((page_ - 1) * FINDINGS_PAGE_SIZE, page_ * FINDINGS_PAGE_SIZE);

  return (
    <Panel className="p-5">
      <p className="sage-mono text-[11px] uppercase tracking-[0.18em] text-[var(--sage-text-muted)]">{title}</p>
      {issues.length > 0 ? (
        <>
          <div className="mt-4 flex flex-wrap gap-2">
            {SEVERITIES.map((sev) => (
              <SeverityTab key={sev} severity={sev} count={counts[sev]} active={sev === activeSeverity} onSelect={() => selectSeverity(sev)} />
            ))}
          </div>
          <div className="mt-4 space-y-3">
            {pageItems.map(({ issue, index }, positionOnPage) => (
              <FindingReviewCard
                key={`${issue.issue}-${index}`}
                issue={issue}
                source={issue.source}
                defaultOpen={positionOnPage === 0}
                fix={fixes[`${issue.source}-${index}`]}
                state={states[`${issue.source}-${index}`]}
                applyDisabledByOverlap={hasOverlappingGeneratedPatch(`${issue.source}-${index}`, fixes[`${issue.source}-${index}`], fixes)}
                explanation={explanations[`${issue.source}-${index}`]}
                loading={loadingFix === `${issue.source}-${index}`}
                explaining={loadingExplain === `${issue.source}-${index}`}
                onGenerateFix={() => onGenerateFix?.(issue, `${issue.source}-${index}`)}
                onExplain={() => onExplain?.(issue, `${issue.source}-${index}`)}
                onApplyFix={() => onApplyFix?.(`${issue.source}-${index}`)}
              />
            ))}
          </div>
          {visible.length > FINDINGS_PAGE_SIZE && (
            <FindingsPager page={page_} totalPages={totalPages} onPrev={() => setPage(page_ - 1)} onNext={() => setPage(page_ + 1)} />
          )}
        </>
      ) : (
        <p className="mt-4 rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3 text-sm text-[var(--sage-text-muted)]">{empty}</p>
      )}
    </Panel>
  );
}

function SeverityTab({ severity, count, active, onSelect }) {
  const disabled = !count;
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onSelect}
      disabled={disabled}
      aria-pressed={active}
      className={cx(
        "sage-mono rounded-md border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition",
        disabled
          ? "cursor-not-allowed border-white/5 bg-white/[0.02] text-[var(--sage-text-muted)] opacity-40"
          : active
          ? severityTone(severity)
          : "border-[var(--sage-border-subtle)] bg-black/20 text-[var(--sage-text-secondary)] hover:bg-white/[0.04]"
      )}
    >
      {severity[0].toUpperCase()}{severity.slice(1)} {count}
    </button>
  );
}

function FindingsPager({ page, totalPages, onPrev, onNext }) {
  return (
    <div className="mt-4 flex items-center justify-center gap-4">
      <button type="button" onClick={onPrev} disabled={page <= 1} className="sage-button-secondary disabled:opacity-40">&lt; Previous</button>
      <span className="sage-mono text-xs text-[var(--sage-text-muted)]">Page {page} of {totalPages}</span>
      <button type="button" onClick={onNext} disabled={page >= totalPages} className="sage-button-secondary disabled:opacity-40">Next &gt;</button>
    </div>
  );
}

function FindingReviewCard({
  issue,
  source,
  defaultOpen,
  fix,
  state,
  applyDisabledByOverlap,
  explanation,
  loading,
  explaining,
  onGenerateFix,
  onExplain,
  onApplyFix,
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  const title = issue.issue || "Review finding";
  const sourceLabel = source === "deterministic" ? "High confidence" : "AI-assisted review";
  const problem = [issue.issue, issue.evidence ? `The highlighted code supports this finding.` : `Line ${issue.line || "?"} needs review.`].filter(Boolean);
  const why = [issue.fix_suggestion || "This can affect correctness, reliability, or maintainability."];
  const guidance = issue.knowledge_standards || [];
  return (
    <article className="rounded-xl border border-[var(--sage-border-subtle)] bg-black/20">
      <button type="button" onClick={() => setOpen(!open)} className="w-full p-4 text-left">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={issue.severity} />
          <span className="sage-mono text-xs text-[var(--sage-text-muted)]">line {issue.line || "?"}</span>
          <span className="sage-mono text-xs text-[var(--sage-text-muted)]">{sourceLabel}</span>
          {state && <span className="sage-mono rounded bg-[var(--sage-accent-soft)] px-2 py-0.5 text-[10px] uppercase text-[var(--sage-accent)]">{state}</span>}
        </div>
        <h4 className="mt-3 text-sm font-semibold">{title}</h4>
        <p className="mt-1 text-xs text-[var(--sage-text-muted)]">{issue.category} · confidence {Math.round((issue.confidence || 0) * 100)}%</p>
      </button>
      {open && (
        <div className="space-y-4 border-t border-[var(--sage-border-subtle)] p-4">
          <BriefBullets title="Problem" items={problem} />
          <BriefBullets title="Why it matters" items={why} />
          {issue.evidence && (
            <section>
              <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Evidence</p>
              <pre className="sage-mono mt-2 overflow-auto rounded-lg border border-[var(--sage-border-subtle)] bg-black/30 p-3 text-xs text-[var(--sage-text-secondary)]">{issue.evidence}</pre>
            </section>
          )}
          <BriefBullets title="Recommended fix" items={[issue.fix_suggestion || "Generate a scoped fix proposal."]} />
          {guidance.length > 0 && (
            <section>
              <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Engineering guidance</p>
              <div className="mt-2 space-y-2">
                {guidance.slice(0, 3).map((record) => (
                  <div key={`${record.rule_id}-${record.title}`} className="rounded-lg border border-[var(--sage-border-subtle)] bg-black/20 p-3">
                    <p className="text-sm font-medium">{record.title}</p>
                    <p className="mt-1 text-xs capitalize text-[var(--sage-text-muted)]">{record.category || "engineering"}</p>
                  </div>
                ))}
              </div>
            </section>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onExplain} disabled={explaining} className="sage-button-secondary disabled:opacity-50">{explaining ? "Explaining..." : "Explain"}</button>
            <button type="button" onClick={onGenerateFix} disabled={loading} className="sage-button-primary disabled:opacity-50">{fix ? "Regenerate Fix" : "Generate Fix"}</button>
            <button type="button" disabled={!fix} className="sage-button-secondary disabled:opacity-50">View Diff</button>
            <button type="button" onClick={onApplyFix} disabled={!fix?.can_apply || applyDisabledByOverlap || state === "Fix applied"} className="sage-button-secondary disabled:opacity-50">Apply Fix</button>
          </div>
          {explanation && (
            <section className="rounded-lg border border-[var(--sage-border-subtle)] bg-black/25 p-3">
              <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Explanation</p>
              <p className="mt-2 text-sm leading-relaxed text-[var(--sage-text-secondary)]">{explanation}</p>
            </section>
          )}
          {fix && <FixPanel fix={fix} />}
        </div>
      )}
    </article>
  );
}

function BriefBullets({ title, items }) {
  return (
    <section>
      <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">{title}</p>
      <ul className="mt-2 space-y-1 text-sm text-[var(--sage-text-secondary)]">
        {items.slice(0, 2).map((item, i) => <li key={i}>• {item}</li>)}
      </ul>
    </section>
  );
}

function FixPanel({ fix }) {
  return (
    <div className="rounded-xl border border-[var(--sage-border-subtle)] bg-black/25 p-4">
      <p className="sage-mono text-[10px] uppercase tracking-[0.16em] text-[var(--sage-accent)]">Fix preview</p>
      {fix.summary && <p className="mt-2 text-sm font-medium">{fix.summary}</p>}
      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        <div>
          <p className="sage-mono mb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Original</p>
          <pre className="sage-mono max-h-64 overflow-auto rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-xs text-[var(--sage-text-secondary)]">{fix.original_code || fix.original_snippet}</pre>
        </div>
        <div>
          <p className="sage-mono mb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--sage-text-muted)]">Proposed preview</p>
          <pre className="sage-mono max-h-64 overflow-auto rounded-lg border border-[var(--sage-border-accent)] bg-[var(--sage-accent-soft)] p-3 text-xs text-[var(--sage-text-primary)]">{fix.fixed_code || fix.proposed_fix}</pre>
        </div>
      </div>
      {fix.diff && <pre className="sage-mono mt-3 max-h-64 overflow-auto rounded-lg border border-[var(--sage-border-subtle)] bg-black/30 p-3 text-xs text-[var(--sage-text-secondary)]">{fix.diff}</pre>}
      {(fix.explanation_bullets?.length > 0 || fix.explanation) && (
        <BriefBullets title="Explanation" items={fix.explanation_bullets?.length ? fix.explanation_bullets : [fix.explanation]} />
      )}
      {!fix.can_apply && (
        <p className="mt-3 text-xs text-[var(--sage-warning)]">
          {patchReasonMessage(fix.apply_failure_reason)}
        </p>
      )}
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  const sessionId = useSessionId();
  const [activeView, setActiveView] = useState("Overview");
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("javascript");
  const [reviewResult, setReviewResult] = useState(null);
  const [reviewVersion, setReviewVersion] = useState(0);
  const [projectBundle, setProjectBundle] = useState({ id: null, project: null, score: null, sourceType: "ZIP" });
  const [selectedFinding, setSelectedFinding] = useState(0);
  const [questionSeed, setQuestionSeed] = useState("");

  const project = projectBundle.project ? { ...projectBundle.project, _id: projectBundle.id } : null;

  let content;
  if (activeView === "Analyze") {
    content = (
      <div className="space-y-6">
        <AnalyzePage
          code={code}
          setCode={setCode}
          language={language}
          setLanguage={setLanguage}
          sessionId={sessionId}
          reviewResult={reviewResult}
          setReviewResult={(data) => {
            setReviewResult(data);
            setReviewVersion((version) => version + 1);
          }}
          setProjectBundle={setProjectBundle}
          setActiveView={setActiveView}
        />
        <PasteReviewResults
          key={reviewVersion}
          result={reviewResult}
          code={code}
          setCode={setCode}
          language={language}
          sessionId={sessionId}
          setReviewResult={(data) => {
            setReviewResult(data);
            setReviewVersion((version) => version + 1);
          }}
        />
      </div>
    );
  } else if (activeView === "Findings") {
    content = <FindingsPage project={project} selectedFinding={selectedFinding} setSelectedFinding={setSelectedFinding} />;
  } else if (activeView === "Ask AI") {
    content = <AskAiPage project={project} questionSeed={questionSeed} setQuestionSeed={setQuestionSeed} />;
  } else if (activeView === "History") {
    content = <HistoryPage sessionId={sessionId} />;
  } else {
    content = (
      <OverviewPage
        project={project}
        score={projectBundle.score}
        setActiveView={setActiveView}
        setQuestionSeed={setQuestionSeed}
        setSelectedFinding={setSelectedFinding}
      />
    );
  }

  return (
    <AppShell activeView={activeView} setActiveView={setActiveView} project={project} score={projectBundle.score} sourceType={projectBundle.sourceType}>
      <AnimatePresence mode="wait">
        <motion.div key={activeView} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.16 }}>
          {content}
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}

