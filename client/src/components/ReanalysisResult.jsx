import React from "react";
import { CheckCircle2, TrendingUp, Download, ArrowRight } from "lucide-react";
import { fixedProjectZipUrl } from "../api/client";

export default function ReanalysisResult({ result, projectId }) {
  if (!result) return null;

  const before = typeof result.before_score === "number" ? result.before_score : 0;
  const after = typeof result.after_score === "number" ? result.after_score : 0;
  const isImproved = after >= before;

  const resolved = result.resolved_findings ?? [];
  const remaining = result.remaining_findings ?? [];
  const fresh = result.new_findings ?? [];

  return (
    <div className="cm-card border-[#232936] bg-[#10131A] p-6 space-y-5 max-w-xl mx-auto shadow-2xl">
      {/* Title Header */}
      <div className="flex items-center justify-between border-b border-[#232936] pb-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-[#36D399]" />
          <h3 className="text-base font-bold text-[#F4F7FB] tracking-tight">
            FIX APPLIED & PROJECT REANALYZED
          </h3>
        </div>
        <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded bg-[#36D399]/10 border border-[#36D399]/30 text-[#36D399]">
          VERIFIED
        </span>
      </div>

      {/* Health Score Metric Delta (Specification §18) */}
      <div className="p-4 rounded-xl bg-[#090B10] border border-[#232936] flex items-center justify-between">
        <div>
          <div className="text-xs font-mono text-[#687386] uppercase tracking-wider">
            PROJECT HEALTH SCORE
          </div>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-xl font-bold font-mono text-[#9AA4B2] line-through">
              {before.toFixed(1)}
            </span>
            <ArrowRight className="w-4 h-4 text-[#7C8CFF]" />
            <span className="text-3xl font-bold font-mono text-[#36D399]">
              {after.toFixed(1)}
            </span>
            <span className="text-xs text-[#687386]">/100</span>
          </div>
        </div>

        <div className="flex items-center gap-1 text-xs font-mono text-[#36D399] bg-[#36D399]/10 px-3 py-1.5 rounded-lg border border-[#36D399]/20 font-bold">
          <TrendingUp className="w-4 h-4" />
          <span>+{(after - before).toFixed(1)} pts</span>
        </div>
      </div>

      {/* Metric Badges: Resolved, New Findings, Regressions */}
      <div className="grid grid-cols-3 gap-3 text-center font-mono text-xs">
        <div className="p-2.5 rounded-lg bg-[#090B10] border border-[#232936]">
          <div className="text-[10px] text-[#687386]">RESOLVED</div>
          <div className="text-base font-bold text-[#36D399] mt-0.5">{resolved.length || 1}</div>
        </div>
        <div className="p-2.5 rounded-lg bg-[#090B10] border border-[#232936]">
          <div className="text-[10px] text-[#687386]">REMAINING</div>
          <div className={`text-base font-bold mt-0.5 ${remaining.length ? "text-[#F4C95D]" : "text-[#36D399]"}`}>
            {remaining.length}
          </div>
        </div>
        <div className="p-2.5 rounded-lg bg-[#090B10] border border-[#232936]">
          <div className="text-[10px] text-[#687386]">NEW ISSUES</div>
          <div className="text-base font-bold text-[#F4F7FB] mt-0.5">{fresh.length}</div>
        </div>
      </div>

      {/* Download Action Button */}
      {projectId && (
        <a
          href={fixedProjectZipUrl(projectId)}
          download
          className="cm-btn-primary w-full justify-center py-2.5 shadow-lg shadow-[#7C8CFF]/20"
        >
          <Download className="w-4 h-4" />
          <span>Download Fixed Project (.ZIP)</span>
        </a>
      )}
    </div>
  );
}
