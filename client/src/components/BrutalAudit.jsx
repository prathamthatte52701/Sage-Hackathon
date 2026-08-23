import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  FileCode2,
  Flame,
  Gauge,
  Hammer,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Target,
  XCircle,
} from "lucide-react";
import { runBrutalAudit } from "../api/client";

const CATEGORY_LABELS = {
  security: "Security",
  architecture: "Architecture",
  reliability: "Reliability",
  maintainability: "Maintainability",
  code_quality: "Code Quality",
  production_readiness: "Production Readiness",
};

const SEVERITY_STYLE = {
  critical: { text: "text-[#FF405A]", bg: "bg-[#FF405A]/10", border: "border-[#FF405A]/35" },
  high: { text: "text-[#FF8A65]", bg: "bg-[#FF8A65]/10", border: "border-[#FF8A65]/35" },
  medium: { text: "text-[#F4C95D]", bg: "bg-[#F4C95D]/10", border: "border-[#F4C95D]/35" },
  low: { text: "text-[#36D399]", bg: "bg-[#36D399]/10", border: "border-[#36D399]/35" },
};

function severityStyle(severity) {
  return SEVERITY_STYLE[severity] || SEVERITY_STYLE.low;
}

function scoreColor(score) {
  if (score >= 8) return "text-[#36D399]";
  if (score >= 6) return "text-[#F4C95D]";
  return "text-[#FF6674]";
}

function EvidenceList({ evidence }) {
  if (!evidence || evidence.length === 0) {
    return <span className="text-[10px] text-[#687386] italic">No verified file evidence retained</span>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {evidence.map((item, index) => (
        <span
          key={`${item.file}-${item.line}-${index}`}
          className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#090B10] border border-[#232936] text-[#9AA4B2]"
        >
          <FileCode2 className="w-2.5 h-2.5 text-[#FF8A65]" />
          {item.file || "repo evidence"}
          {item.line ? `:${item.line}` : ""}
          {item.function ? ` · ${item.function}()` : ""}
          {item.route ? ` · ${item.route}` : ""}
        </span>
      ))}
    </div>
  );
}

function SnapshotItem({ label, value }) {
  return (
    <div className="p-3 rounded-lg bg-[#0D0F14] border border-[#232936]">
      <div className="text-lg font-bold text-[#F4F7FB]">{value ?? 0}</div>
      <div className="text-[10px] uppercase tracking-wide text-[#687386] font-mono">{label}</div>
    </div>
  );
}

function CategoryScore({ category, score }) {
  const pct = Math.max(0, Math.min(100, (score || 0) * 10));
  return (
    <div className="p-3.5 rounded-lg border border-[#232936] bg-[#10131A] space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold text-[#F4F7FB]">{CATEGORY_LABELS[category] || category}</span>
        <span className={`text-sm font-mono font-bold ${scoreColor(score)}`}>{Number(score || 0).toFixed(1)}/10</span>
      </div>
      <div className="h-1.5 rounded-full bg-[#090B10] border border-[#232936] overflow-hidden">
        <div className="h-full bg-[#FF8A65]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function CriticismCard({ item }) {
  const style = severityStyle(item.severity);
  return (
    <div className={`p-4 rounded-xl border ${style.border} bg-[#10131A] space-y-3`}>
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-sm font-bold text-[#F4F7FB]">{item.title}</h4>
        <span className={`shrink-0 text-[10px] font-mono font-bold uppercase px-2 py-0.5 rounded ${style.bg} ${style.text} border ${style.border}`}>
          {item.severity}
        </span>
      </div>
      <div className="text-[10px] font-mono uppercase tracking-wide text-[#FF8A65]">
        {CATEGORY_LABELS[item.category] || item.category}
      </div>
      {item.reason && <p className="text-xs text-[#C7CDD6] leading-relaxed">{item.reason}</p>}
      <EvidenceList evidence={item.evidence} />
      {item.impact && (
        <p className="text-xs text-[#9AA4B2]">
          <span className="text-[#687386] font-medium">Impact: </span>
          {item.impact}
        </p>
      )}
      {item.improvement && (
        <div className="pt-2 border-t border-[#232936] flex items-start gap-2 text-xs text-[#C7CDD6]">
          <Hammer className="w-3.5 h-3.5 text-[#36D399] mt-0.5 shrink-0" />
          <span>{item.improvement}</span>
        </div>
      )}
    </div>
  );
}

export default function BrutalAudit({ projectId, project }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const categories = useMemo(() => {
    const scores = report?.category_scores || {};
    return Object.keys(CATEGORY_LABELS).map((category) => ({ category, score: Number(scores[category] || 0) }));
  }, [report]);

  const run = async () => {
    if (!projectId || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await runBrutalAudit(projectId);
      setReport(data);
      if (data?.error) setError(data.summary || "Brutal Audit could not complete.");
    } catch (err) {
      setError(err.message || "Brutal Audit failed. Please retry.");
    } finally {
      setLoading(false);
    }
  };

  if (!projectId) {
    return (
      <div className="max-w-5xl mx-auto p-12 text-center text-xs text-[#687386] border border-[#232936] rounded-xl bg-[#10131A]">
        Import a repository first to unlock Brutal Audit.
      </div>
    );
  }

  const snapshot = report?.repository_snapshot || {};

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-[#232936] pb-4">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-[#FF8A65]/15 border border-[#FF8A65]/35 flex items-center justify-center text-[#FF8A65]">
            <Flame className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-xl font-black tracking-tight text-[#F4F7FB]">BRUTAL AUDIT</h2>
            <p className="text-xs text-[#9AA4B2]">No sugarcoating. How production-ready is this repository?</p>
          </div>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 px-3.5 py-2 rounded-lg text-xs font-bold bg-[#FF8A65]/15 border border-[#FF8A65]/40 text-[#FF8A65] hover:bg-[#FF8A65]/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {report ? "Re-run Brutal Audit" : "Run Brutal Audit"}
        </button>
      </div>

      {!report && !loading && !error && (
        <div className="p-12 text-center text-xs text-[#687386] border border-[#232936] rounded-xl bg-[#10131A] space-y-2">
          <Flame className="w-8 h-8 text-[#343D50] mx-auto" />
          <p>No Brutal Audit has been run for {project?.name || "this repository"} yet.</p>
          <p className="text-[#4B5565]">It reuses the uploaded project, calls Groq directly, and does not use RAG or change Findings.</p>
        </div>
      )}

      {loading && (
        <div className="p-12 text-center text-xs text-[#9AA4B2] border border-[#232936] rounded-xl bg-[#10131A] flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-[#FF8A65] animate-spin" />
          Running a strict production-readiness review...
        </div>
      )}

      {error && !loading && (
        <div className="p-5 rounded-xl border border-[#FF5D73]/30 bg-[#FF5D73]/5 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-[#FF5D73] shrink-0 mt-0.5" />
          <div className="flex-1 space-y-2">
            <p className="text-xs text-[#F4F7FB]">{error}</p>
            <button onClick={run} className="text-xs font-semibold text-[#FF5D73] hover:underline">
              Retry
            </button>
          </div>
        </div>
      )}

      {report && !report.error && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 p-5 rounded-xl border border-[#232936] bg-[#10131A] space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold">Senior Engineer Read</span>
              <p className="text-sm text-[#C7CDD6] leading-relaxed">{report.summary}</p>
              <div className="flex flex-wrap gap-2 pt-2">
                {(snapshot.languages || []).map((item) => (
                  <span key={item} className="text-[10px] font-mono px-2 py-1 rounded bg-[#0D0F14] border border-[#232936] text-[#9AA4B2]">
                    {item}
                  </span>
                ))}
                {(snapshot.frameworks || []).map((item) => (
                  <span key={item} className="text-[10px] font-mono px-2 py-1 rounded bg-[#0D0F14] border border-[#232936] text-[#9AA4B2]">
                    {item}
                  </span>
                ))}
              </div>
            </div>
            <div className="p-5 rounded-xl border border-[#FF8A65]/35 bg-[#FF8A65]/10 flex flex-col justify-center items-center text-center space-y-2">
              <Gauge className="w-5 h-5 text-[#FF8A65]" />
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#9AA4B2] font-semibold">Overall Score</span>
              <span className={`text-4xl font-black ${scoreColor(report.overall_score)}`}>
                {Number(report.overall_score || 0).toFixed(1)}
                <span className="text-sm text-[#687386]"> / 10</span>
              </span>
              <span className="text-xs font-mono font-bold uppercase text-[#F4F7FB]">{report.verdict}</span>
            </div>
          </div>

          <section className="space-y-3">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
              <BarChart3 className="w-3.5 h-3.5" /> Category Scores
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {categories.map((item) => (
                <CategoryScore key={item.category} category={item.category} score={item.score} />
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
              <Target className="w-3.5 h-3.5" /> Repository Snapshot
            </span>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-5 gap-3">
              <SnapshotItem label="Files" value={snapshot.files_analyzed} />
              <SnapshotItem label="Source Files" value={snapshot.source_files_analyzed} />
              <SnapshotItem label="API Entry Points" value={snapshot.api_entry_points} />
              <SnapshotItem label="Functions / Classes" value={snapshot.functions_classes} />
              <SnapshotItem label="DB Areas" value={snapshot.database_interaction_areas} />
              <SnapshotItem label="External Integrations" value={snapshot.external_integrations} />
              <SnapshotItem label="Privileged Ops" value={snapshot.privileged_operations} />
              <SnapshotItem label="Auth Components" value={snapshot.authentication_components} />
              <SnapshotItem label="Filesystem Usage" value={snapshot.filesystem_usage} />
              <SnapshotItem label="Large Functions" value={snapshot.large_functions} />
            </div>
          </section>

          {report.code_review_rejections?.length > 0 && (
            <section className="space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5" /> What I Would Reject In Code Review
              </span>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {report.code_review_rejections.map((item, index) => (
                  <CriticismCard key={`${item.title}-${index}`} item={item} />
                ))}
              </div>
            </section>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <section className="p-5 rounded-xl border border-[#232936] bg-[#10131A] space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
                <XCircle className="w-3.5 h-3.5 text-[#FF6674]" /> Weakest Areas
              </span>
              <div className="space-y-2">
                {(report.weakest_areas || []).map((item, index) => (
                  <div key={item.category} className="flex items-center justify-between text-xs border-b border-[#232936] pb-2 last:border-0 last:pb-0">
                    <span className="text-[#C7CDD6]">#{index + 1} {CATEGORY_LABELS[item.category] || item.category}</span>
                    <span className={`font-mono font-bold ${scoreColor(item.score)}`}>{Number(item.score || 0).toFixed(1)}/10</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="p-5 rounded-xl border border-[#232936] bg-[#10131A] space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-[#36D399]" /> Strongest Areas
              </span>
              {report.strongest_areas?.length ? (
                <ul className="space-y-2">
                  {report.strongest_areas.map((item, index) => (
                    <li key={index} className="text-xs text-[#C7CDD6] flex gap-2">
                      <span className="font-mono text-[#36D399]">{index + 1}.</span>
                      {item}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[#687386]">No strongest areas were claimed without evidence.</p>
              )}
            </section>
          </div>

          {report.production_blockers?.length > 0 && (
            <section className="p-5 rounded-xl border border-[#FF5D73]/30 bg-[#FF5D73]/5 space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#FF5D73] font-semibold">Not Ready Because</span>
              <ul className="space-y-2">
                {report.production_blockers.map((item, index) => (
                  <li key={index} className="text-xs text-[#F4F7FB] flex gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-[#FF5D73] shrink-0 mt-0.5" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {report.top_improvements?.length > 0 && (
            <section className="p-5 rounded-xl border border-[#36D399]/25 bg-[#36D399]/5 space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#36D399] font-semibold flex items-center gap-1.5">
                <Hammer className="w-3.5 h-3.5" /> How To Reach 9/10
              </span>
              <ol className="space-y-2">
                {report.top_improvements.map((item, index) => (
                  <li key={index} className="text-xs text-[#C7CDD6] flex gap-2">
                    <span className="font-mono font-bold text-[#36D399] shrink-0">{index + 1}.</span>
                    {item}
                  </li>
                ))}
              </ol>
            </section>
          )}

          <p className="text-[10px] text-[#4B5565] pt-2 border-t border-[#232936]">
            Brutal Audit analyzed {report.files_analyzed?.length || 0} bounded source file(s). It uses Groq directly, no
            RAG/vector retrieval, no second upload, and no changes to normal CODE MASTER AI findings.
          </p>
        </div>
      )}
    </div>
  );
}
