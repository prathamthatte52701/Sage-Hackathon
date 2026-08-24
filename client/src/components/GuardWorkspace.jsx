import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  GitCommit,
  GitPullRequest,
  Loader2,
  Play,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  getCommitGuardStatus,
  getPrGuardStatus,
  startCommitGuard,
  startPrGuard,
} from "../api/client";

const TERMINAL = new Set(["completed", "complete", "failed", "cancelled"]);
const PR_GUARD_STATE_KEY = "code_master_ai_pr_guard_state";

function verdictTone(verdict) {
  if (verdict === "PASS") return "text-[#36D399] border-[#36D399]/35 bg-[#36D399]/10";
  if (verdict === "BLOCK") return "text-[#FF5D73] border-[#FF5D73]/35 bg-[#FF5D73]/10";
  return "text-[#F4C95D] border-[#F4C95D]/35 bg-[#F4C95D]/10";
}

function statusIcon(status) {
  if (status === "failed") return <XCircle className="w-4 h-4 text-[#FF5D73]" />;
  if (TERMINAL.has(status)) return <CheckCircle2 className="w-4 h-4 text-[#36D399]" />;
  if (status) return <Loader2 className="w-4 h-4 animate-spin text-[#7C8CFF]" />;
  return <ShieldCheck className="w-4 h-4 text-[#7C8CFF]" />;
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-[#232936] bg-[#090B10] p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[#687386]">{label}</div>
      <div className="mt-1 text-lg font-bold text-[#F4F7FB]">{value}</div>
    </div>
  );
}

function shortSha(value) {
  return value ? String(value).slice(0, 7) : "empty";
}

function ChangedFiles({ files = [] }) {
  if (!files.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF]">Changed Files</h3>
      <div className="space-y-2">
        {files.slice(0, 12).map((file, index) => (
          <div key={`${file.path}-${index}`} className="rounded-lg border border-[#232936] bg-[#090B10] p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <span className="font-mono uppercase text-[#F4C95D]">{file.status || "modified"}</span>
                <span className="ml-2 font-semibold text-[#F4F7FB] break-all">
                  {file.previous_path ? `${file.previous_path} -> ${file.path}` : file.path}
                </span>
              </div>
              <span className="font-mono text-[#687386]">+{file.additions || 0} / -{file.deletions || 0}</span>
            </div>
            {file.patch && <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-[#9AA4B2]">{file.patch}</pre>}
          </div>
        ))}
      </div>
    </div>
  );
}

function PrHeaderMeta({ report }) {
  const pr = report.pr || {};
  return (
    <div className="space-y-1">
      {pr.title && <div className="text-sm font-semibold text-[#F4F7FB]">{pr.title}</div>}
      <div className="flex flex-wrap gap-2 text-[11px] font-mono text-[#687386]">
        {pr.state && <span>{String(pr.state).toUpperCase()}</span>}
        {pr.base_branch && pr.head_branch && <span>{pr.base_branch} {"<-"} {pr.head_branch}</span>}
        {pr.author && <span>@{pr.author}</span>}
        <span>{pr.commit_count || 0} commits</span>
        <span>{pr.changed_file_count || 0} files</span>
        <span>+{pr.additions || 0} / -{pr.deletions || 0}</span>
        <span>BASE {shortSha(report.merge_base || report.comparison_base)}</span>
        <span>HEAD {shortSha(report.head_sha || report.comparison_head)}</span>
        {report.truncated && <span>PYTHON ANALYSIS BOUNDED</span>}
      </div>
    </div>
  );
}

function FindingList({ title, items = [] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF]">{title}</h3>
      <div className="space-y-2">
        {items.slice(0, 8).map((item, index) => (
          <div key={`${item.finding_id || item.rule_id || item.file || title}-${index}`} className="rounded-lg border border-[#232936] bg-[#090B10] p-3 text-xs">
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-[#F4F7FB]">{item.title || item.rule_id || item.rule || "Finding"}</span>
              <span className="font-mono uppercase text-[#F4C95D]">{item.severity || "risk"}</span>
            </div>
            <div className="mt-1 text-[#9AA4B2]">{item.file || item.path || "Unknown file"}{item.line ? `:${item.line}` : ""}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ImpactDetails({ report }) {
  const summary = report.blast_delta?.summary || {};
  const components = report.blast_delta?.components || [];
  const tags = report.sensitive_areas || [];
  if (!components.length && !tags.length) return null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {components.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF]">Impact</h3>
          <div className="rounded-lg border border-[#232936] bg-[#090B10] p-3 text-xs text-[#C8D0DA]">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <div className="font-mono uppercase text-[#687386]">Routes Before</div>
                <div className="mt-1 text-base font-bold text-[#F4F7FB]">{summary.affected_routes_before ?? 0}</div>
              </div>
              <div>
                <div className="font-mono uppercase text-[#687386]">Routes After</div>
                <div className="mt-1 text-base font-bold text-[#F4F7FB]">{summary.affected_routes_after ?? 0}</div>
              </div>
            </div>
            <div className="mt-3 space-y-2">
              {components.slice(0, 6).map((component) => (
                <div key={component.path} className="flex items-center justify-between gap-3 border-t border-[#232936] pt-2">
                  <span className="break-all text-[#F4F7FB]">{component.path}</span>
                  <span className="font-mono text-[#9AA4B2]">{component.before_score} {"->"} {component.after_score}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {tags.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF]">Sensitive Areas</h3>
          <div className="flex flex-wrap gap-2 rounded-lg border border-[#232936] bg-[#090B10] p-3">
            {tags.map((tag) => (
              <span key={tag} className="rounded-md border border-[#F4C95D]/30 bg-[#F4C95D]/10 px-2 py-1 text-[11px] font-mono uppercase text-[#F4C95D]">
                {tag.replaceAll("_", " ")}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function QualityDeltaDetails({ quality }) {
  const dimensions = quality?.dimensions || {};
  const entries = Object.entries(dimensions);
  if (!entries.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF]">Quality Delta</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {entries.map(([name, item]) => (
          <div key={name} className="rounded-lg border border-[#232936] bg-[#090B10] p-3">
            <div className="text-[10px] font-mono uppercase tracking-wider text-[#687386]">
              {name.replaceAll("_", " ")}
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-3">
              <span className="font-mono text-sm text-[#F4F7FB]">{item.before} {"->"} {item.after}</span>
              <span className={`text-[10px] font-mono ${item.direction === "DEGRADED" ? "text-[#FF5D73]" : item.direction === "IMPROVED" ? "text-[#36D399]" : "text-[#9AA4B2]"}`}>
                {item.direction}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReportView({ report, mode }) {
  if (!report) return null;
  const securityDelta = report.security_delta || {};
  const blastSummary = report.blast_delta?.summary || {};
  const changedFiles = report.changed_files || report.pr?.changed_file_count || 0;
  const changedCount = Array.isArray(changedFiles) ? changedFiles.length : changedFiles;
  const qualityDirection = report.quality_delta?.direction || "N/A";
  const sensitiveCount = report.sensitive_areas?.length || 0;
  const isCommit = mode === "commit";
  const docsOnly = isCommit && report.risk_score === 0 && !securityDelta.new?.length && !securityDelta.resolved?.length && !report.blast_delta?.components?.length;

  return (
    <div className="cm-card border-[#232936] bg-[#10131A] p-5 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-lg border px-3 py-1 text-xs font-bold ${verdictTone(report.verdict)}`}>
              {report.verdict || "REVIEW"}
            </span>
            <span className="text-xs font-mono text-[#9AA4B2]">Risk {report.risk_score ?? "N/A"}/100</span>
            {report.stale && <span className="text-xs font-mono text-[#F4C95D]">STALE</span>}
          </div>
          <h2 className="text-lg font-extrabold text-[#F4F7FB]">
            {mode === "pr" ? `PR #${report.pr?.number || ""}` : report.commit_message || "Latest Commit"}
          </h2>
          {!isCommit && <PrHeaderMeta report={report} />}
          {isCommit && (
            <div className="flex flex-wrap gap-2 text-[11px] font-mono text-[#687386]">
              <span>HEAD {shortSha(report.head_sha)}</span>
              <span>BASE {shortSha(report.base_sha)}</span>
              {report.comparison_type === "initial" && <span>INITIAL COMMIT</span>}
              {report.merge_commit && <span>MERGE COMMIT - FIRST PARENT</span>}
              {report.truncated && <span>PYTHON ANALYSIS BOUNDED</span>}
              {docsOnly && <span>NO PYTHON SOURCE CHANGED</span>}
            </div>
          )}
          <p className="text-sm text-[#9AA4B2]">{report.summary || "Guard analysis completed."}</p>
        </div>
      </div>

      {report.stale && (
        <div className="rounded-lg border border-[#F4C95D]/35 bg-[#F4C95D]/10 p-3 text-xs text-[#F4C95D]">
          A newer PR version is available. This report analyzed HEAD {shortSha(report.head_sha || report.comparison_head)}; current HEAD is {shortSha(report.current_head_sha)}.
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Metric label="Changed" value={changedCount} />
        <Metric label="New Findings" value={securityDelta.new?.length || 0} />
        <Metric label="Resolved" value={securityDelta.resolved?.length || 0} />
        <Metric label="Blast Delta" value={blastSummary.overall_delta ?? 0} />
        <Metric label={mode === "pr" ? "Quality" : "Sensitive"} value={mode === "pr" ? qualityDirection : sensitiveCount} />
      </div>

      <ChangedFiles files={report.changed_files || []} />

      {(report.ai_explanation || report.ai_error) && (
        <div className="rounded-lg border border-[#232936] bg-[#090B10] p-4 text-sm">
          <div className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF] mb-2">Explanation</div>
          <p className="text-[#C8D0DA] leading-relaxed">{report.ai_explanation || `Explanation unavailable: ${report.ai_error}`}</p>
        </div>
      )}

      {report.hacker_review?.hypotheses?.length > 0 && (
        <div className="rounded-lg border border-[#232936] bg-[#090B10] p-4 text-sm">
          <div className="text-xs font-mono uppercase tracking-wider text-[#7C8CFF] mb-2">PR Hacker Review</div>
          <p className="text-[#9AA4B2] mb-3">{report.hacker_review.summary}</p>
          <div className="space-y-2">
            {report.hacker_review.hypotheses.slice(0, 4).map((item, index) => (
              <div key={`${item.title || "hypothesis"}-${index}`} className="text-xs text-[#C8D0DA]">
                {typeof item === "string" ? (
                  item
                ) : (
                  <>
                    <span className="font-semibold text-[#F4F7FB]">{item.title || "Hypothesis"}:</span> {item.rationale || item.description}
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!isCommit && <QualityDeltaDetails quality={report.quality_delta} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <FindingList title="New Findings" items={securityDelta.new || []} />
        <FindingList title="Resolved Findings" items={securityDelta.resolved || []} />
        <FindingList title="Persisting Findings" items={securityDelta.persisting || []} />
      </div>

      <ImpactDetails report={report} />
    </div>
  );
}

export default function GuardWorkspace({ mode, project }) {
  const projectId = project?.project_id;
  const [prNumber, setPrNumber] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const storageKey = mode === "pr" && projectId ? `${PR_GUARD_STATE_KEY}:${projectId}` : "";

  const config = useMemo(() => {
    if (mode === "pr") {
      return {
        icon: GitPullRequest,
        title: "PR Guard",
        subtitle: "Review one GitHub pull request as a combined, read-only change set.",
      };
    }
    return {
      icon: GitCommit,
      title: "Commit Guard",
      subtitle: "Check the latest commit against Defender, impact, sensitive-surface and validity signals.",
    };
  }, [mode]);

  useEffect(() => {
    if (!projectId || !status || TERMINAL.has(status.status)) return undefined;
    const runId = status.run_id || status.job_id;
    let cancelled = false;
    let timer = null;

    async function poll() {
      try {
        const next = mode === "pr" ? await getPrGuardStatus(projectId, runId) : await getCommitGuardStatus(projectId);
        if (!cancelled) setStatus(next);
        if (!cancelled && !TERMINAL.has(next.status)) timer = window.setTimeout(poll, 2000);
      } catch (err) {
        if (!cancelled) setError(err.message || `Could not refresh ${config.title}.`);
      }
    }

    timer = window.setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [config.title, mode, projectId, status]);

  useEffect(() => {
    if (mode !== "pr" || !projectId || status) return;
    let saved = null;
    try {
      saved = JSON.parse(window.localStorage.getItem(storageKey) || "null");
    } catch {
      saved = null;
    }
    if (!saved?.pull_request_number) return;
    setPrNumber(String(saved.pull_request_number));
    getPrGuardStatus(projectId, saved.run_id || null, saved.pull_request_number)
      .then(setStatus)
      .catch(() => {});
  }, [mode, projectId, status, storageKey]);

  const start = async () => {
    if (!projectId || busy) return;
    if (mode === "pr" && !Number.parseInt(prNumber, 10)) {
      setError("Enter a GitHub pull request number.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const data = mode === "pr" ? await startPrGuard(projectId, prNumber) : await startCommitGuard(projectId);
      setStatus(data);
      if (mode === "pr") {
        window.localStorage.setItem(
          storageKey,
          JSON.stringify({ run_id: data.run_id || data.job_id, pull_request_number: Number(prNumber) })
        );
      }
    } catch (err) {
      setError(err.message || `Could not start ${config.title}.`);
    } finally {
      setBusy(false);
    }
  };

  const Icon = config.icon;
  if (!projectId) {
    return (
      <div className="cm-card border-[#232936] bg-[#10131A] p-10 text-center text-sm text-[#9AA4B2]">
        Import a repository first to unlock {config.title}.
      </div>
    );
  }

  const report = status?.report;
  const statusLabel = status?.error || status?.message || (status?.status ? `${config.title} ${status.status}.` : config.subtitle);

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="cm-card border-[#232936] bg-[#10131A] p-5 space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg border border-[#7C8CFF]/30 bg-[#7C8CFF]/10 text-[#7C8CFF] flex items-center justify-center">
              <Icon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-xl font-extrabold text-[#F4F7FB]">{config.title}</h2>
              <p className="mt-1 text-sm text-[#9AA4B2]">{statusLabel}</p>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row sm:items-center gap-2">
            {mode === "pr" && (
              <input
                type="number"
                min="1"
                value={prNumber}
                onChange={(event) => setPrNumber(event.target.value)}
                className="sage-input h-9 w-full sm:w-36 px-3 text-sm"
                placeholder="PR number"
              />
            )}
            <button
              type="button"
              onClick={start}
              disabled={busy || (status?.status && !TERMINAL.has(status.status))}
              className="cm-btn-primary text-xs py-2 disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              <span>{status?.report ? `Re-run ${config.title}` : `Run ${config.title}`}</span>
            </button>
          </div>
        </div>

        {(status || error) && (
          <div className="rounded-lg border border-[#232936] bg-[#090B10] p-3 flex items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2 text-[#9AA4B2]">
              {error ? <AlertTriangle className="w-4 h-4 text-[#F4C95D]" /> : statusIcon(status?.status)}
              <span>{error || status?.error || status?.stage || status?.status || "ready"}</span>
            </div>
            {status?.job_id && <span className="font-mono text-[#687386] truncate max-w-[220px]">{status.job_id}</span>}
          </div>
        )}
      </div>

      <ReportView report={report} mode={mode} />
    </div>
  );
}
