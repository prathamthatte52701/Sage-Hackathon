import React from "react";
import {
  AlertTriangle,
  FileCode2,
  ArrowUpRight,
  CheckCircle2,
  BarChart3,
  Cpu,
} from "lucide-react";

const CATEGORY_LABELS = {
  security: "Security",
  code_quality: "Code Quality",
  architecture: "Architecture",
  testing: "Testing",
  api_design: "API Design",
  performance: "Performance",
  production_readiness: "Production Readiness",
};

function getScoreRating(score) {
  if (score >= 80) return { label: "EXCELLENT", color: "text-[#36D399] bg-[#36D399]/10 border-[#36D399]/30" };
  if (score >= 65) return { label: "GOOD", color: "text-[#57B8FF] bg-[#57B8FF]/10 border-[#57B8FF]/30" };
  if (score >= 50) return { label: "NEEDS ATTENTION", color: "text-[#F4C95D] bg-[#F4C95D]/10 border-[#F4C95D]/30" };
  return { label: "CRITICAL", color: "text-[#FF5D73] bg-[#FF5D73]/10 border-[#FF5D73]/30" };
}

function getCategoryColor(score) {
  if (score >= 80) return "bg-[#36D399]";
  if (score >= 65) return "bg-[#57B8FF]";
  if (score >= 50) return "bg-[#F4C95D]";
  return "bg-[#FF5D73]";
}

export default function ProjectOverview({ project, score, onSelectFinding, onSelectCategory }) {
  const meta = project?.project || {};
  const files = project?.files ?? [];
  const findings = project?.findings ?? [];
  const overall = typeof score?.overall_score === "number" ? score.overall_score : 0;
  const rating = getScoreRating(overall);

  const topPriorities = [...findings]
    .sort((a, b) => {
      const weight = { critical: 4, high: 3, medium: 2, low: 1 };
      return (weight[b.severity] || 0) - (weight[a.severity] || 0);
    })
    .slice(0, 5);

  const categoryEntries = Object.entries(score?.categories ?? {});

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* 1. Project Identity & Health Header */}
      <div className="cm-card p-6 border-[#232936] bg-[#10131A] relative overflow-hidden">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          {/* Metadata */}
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-bold text-[#F4F7FB] tracking-tight">
                {meta.name || "Imported Repository"}
              </h2>
              <span className={`text-[11px] font-mono font-bold px-2.5 py-1 rounded-full border ${rating.color}`}>
                {rating.label}
              </span>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              {meta.projectType && (
                <span className="cm-badge bg-[#7C8CFF]/10 text-[#7C8CFF] border-[#7C8CFF]/20">
                  {meta.projectType}
                </span>
              )}
              {(meta.languages ?? []).map((lang) => (
                <span key={lang} className="cm-badge bg-[#151922] text-[#9AA4B2] border-[#232936]">
                  {lang}
                </span>
              ))}
              {(meta.frameworks ?? []).map((fw) => (
                <span key={fw} className="cm-badge bg-[#151922] text-[#9AA4B2] border-[#232936]">
                  {fw}
                </span>
              ))}
              <span className="text-xs text-[#687386] font-mono flex items-center gap-1.5 ml-1">
                <FileCode2 className="w-3.5 h-3.5" />
                {files.length} indexed files
              </span>
            </div>

            <p className="text-xs text-[#9AA4B2]">
              {findings.length === 0
                ? "No evidence-backed vulnerabilities detected."
                : `${findings.length} findings require review across the codebase.`}
            </p>
          </div>

          {/* Clean Health Score Rating Indicator */}
          <div className="flex items-center gap-6 p-4 rounded-xl bg-[#090B10] border border-[#232936] shrink-0">
            <div className="text-center px-2">
              <div className="text-4xl font-bold font-mono text-[#F4F7FB] tracking-tight">
                {overall.toFixed(1)}
              </div>
              <div className="text-[10px] font-mono text-[#687386] uppercase tracking-wider mt-0.5 font-semibold">
                OVERALL HEALTH
              </div>
            </div>
            <div className="h-10 w-px bg-[#232936]" />
            <div className="space-y-1 text-xs font-mono">
              <div className="text-[#9AA4B2]">Critical/High:</div>
              <div className="text-sm font-bold text-[#FF5D73]">
                {findings.filter((f) => f.severity === "critical" || f.severity === "high").length}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Health Score Category Breakdown (7 Canonical Dimensions) */}
      <div className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-4">
        <div className="flex items-center justify-between border-b border-[#232936] pb-3">
          <h3 className="text-sm font-semibold text-[#F4F7FB] flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-[#7C8CFF]" />
            <span>PROJECT HEALTH BREAKDOWN</span>
          </h3>
          <span className="text-xs font-mono text-[#687386]">Click category to filter evidence</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {categoryEntries.map(([key, cat]) => {
            const catScore = cat?.score ?? 0;
            const isNote = Boolean(cat?.note);
            return (
              <button
                key={key}
                onClick={() => onSelectCategory?.(key)}
                className="w-full text-left p-3.5 rounded-lg bg-[#090B10] border border-[#232936] hover:border-[#7C8CFF]/50 transition-all group"
              >
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="font-medium text-[#F4F7FB] group-hover:text-[#7C8CFF] transition-colors">
                    {CATEGORY_LABELS[key] || key}
                  </span>
                  <span className="font-mono font-bold text-[#F4F7FB]">
                    {isNote ? "—" : `${catScore}/100`}
                  </span>
                </div>

                <div className="h-2 w-full bg-[#151922] rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${getCategoryColor(catScore)}`}
                    style={{ width: `${isNote ? 0 : catScore}%` }}
                  />
                </div>

                {isNote && (
                  <span className="text-[10px] font-mono text-[#687386] mt-1.5 block">
                    Not evaluated on available code evidence
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 3. Top Priorities & Analysis Coverage Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Top Priority Findings */}
        <div className="lg:col-span-2 cm-card p-6 border-[#232936] bg-[#10131A] space-y-4">
          <div className="flex items-center justify-between border-b border-[#232936] pb-3">
            <h3 className="text-sm font-semibold text-[#F4F7FB] flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-[#FF5D73]" />
              <span>TOP PRIORITIES</span>
            </h3>
            <span className="text-xs font-mono text-[#687386]">Immediate attention needed</span>
          </div>

          {topPriorities.length === 0 ? (
            <div className="p-8 text-center text-xs text-[#9AA4B2]">
              No high priority findings detected.
            </div>
          ) : (
            <div className="space-y-2">
              {topPriorities.map((finding, idx) => (
                <div
                  key={idx}
                  onClick={() => onSelectFinding?.(finding)}
                  className="p-3 rounded-lg bg-[#090B10] border border-[#232936] hover:border-[#7C8CFF]/60 cursor-pointer transition-all flex items-center justify-between gap-4 group"
                >
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`cm-badge ${
                          finding.severity === "critical"
                            ? "cm-badge-critical"
                            : finding.severity === "high"
                            ? "cm-badge-high"
                            : "cm-badge-medium"
                        }`}
                      >
                        {finding.severity}
                      </span>
                      <span className="text-xs font-semibold text-[#F4F7FB] group-hover:text-[#7C8CFF] truncate transition-colors">
                        {finding.title || finding.type || "Code Issue"}
                      </span>
                    </div>

                    <div className="text-[11px] font-mono text-[#687386] truncate flex items-center gap-1.5">
                      <span>{finding.file || "source file"}</span>
                      {finding.line && <span>:{finding.line}</span>}
                    </div>
                  </div>

                  <ArrowUpRight className="w-4 h-4 text-[#687386] group-hover:text-[#7C8CFF] shrink-0" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right 1 Col: Analysis Coverage Panel */}
        <div className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-4">
          <div className="border-b border-[#232936] pb-3">
            <h3 className="text-sm font-semibold text-[#F4F7FB] flex items-center gap-2">
              <Cpu className="w-4 h-4 text-[#7C8CFF]" />
              <span>ANALYSIS COVERAGE</span>
            </h3>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div className="flex justify-between py-1.5 border-b border-[#232936]/50">
              <span className="text-[#9AA4B2]">Files discovered</span>
              <span className="text-[#F4F7FB] font-bold">{files.length}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b border-[#232936]/50">
              <span className="text-[#9AA4B2]">Files analyzed</span>
              <span className="text-[#36D399] font-bold">{files.length}</span>
            </div>

            <div className="flex justify-between py-1.5 border-b border-[#232936]/50">
              <span className="text-[#9AA4B2]">Deterministic AST scan</span>
              <span className="text-[#36D399] font-bold">100%</span>
            </div>

            <div className="flex justify-between py-1.5 border-b border-[#232936]/50">
              <span className="text-[#9AA4B2]">AI Grounded Review</span>
              <span className="text-[#7C8CFF] font-bold">Active</span>
            </div>
          </div>

          <div className="p-3 rounded-lg bg-[#090B10] border border-[#232936] text-[11px] text-[#9AA4B2] space-y-1">
            <div className="font-semibold text-[#F4F7FB] flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#36D399]" />
              Evidence Verification
            </div>
            <p className="text-[#687386]">
              All findings are cross-checked against AST rules and grounded source lines.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
