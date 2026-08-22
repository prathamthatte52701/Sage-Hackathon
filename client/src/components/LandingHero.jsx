import React from "react";
import { ShieldCheck, Cpu, GitCommit, CheckCircle2, ArrowRight, Code2, FolderGit2 } from "lucide-react";

export default function LandingHero({ onSelectAction }) {
  return (
    <div className="max-w-4xl mx-auto py-12 px-6 space-y-10 text-center">
      {/* Badge */}
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#7C8CFF]/10 border border-[#7C8CFF]/25 text-[#7C8CFF] text-xs font-mono font-medium">
        <Cpu className="w-3.5 h-3.5" />
        <span>Evidence-Backed Code Review Engine</span>
      </div>

      {/* Main Title & Subtitle */}
      <div className="space-y-4">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-[#F4F7FB]">
          CODE MASTER AI
        </h1>
        <p className="text-lg sm:text-xl text-[#9AA4B2] max-w-2xl mx-auto font-normal leading-relaxed">
          Understand your codebase. Find what matters. Fix it safely.
        </p>
        <p className="text-sm text-[#687386] font-mono">
          Deterministic analysis + AI reasoning grounded in real repository evidence.
        </p>
      </div>

      {/* Action CTA Buttons */}
      <div className="flex flex-wrap justify-center gap-4 pt-2">
        <button
          onClick={() => onSelectAction("projects")}
          className="cm-btn-primary px-6 py-3 text-sm font-semibold shadow-lg shadow-[#7C8CFF]/20"
        >
          <FolderGit2 className="w-4 h-4" />
          <span>Import Project (ZIP / GitHub)</span>
          <ArrowRight className="w-4 h-4 ml-1" />
        </button>

        <button
          onClick={() => onSelectAction("paste_review")}
          className="cm-btn-secondary px-6 py-3 text-sm font-medium"
        >
          <Code2 className="w-4 h-4 text-[#7C8CFF]" />
          <span>Paste Code Snippet</span>
        </button>
      </div>

      {/* Value Proposition Box (Specification §8) */}
      <div className="cm-card p-6 max-w-2xl mx-auto grid grid-cols-1 sm:grid-cols-2 gap-4 text-left border-[#232936] bg-[#10131A]/90">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-[#36D399] shrink-0 mt-0.5" />
          <div>
            <div className="text-xs font-semibold text-[#F4F7FB]">Deterministic Analysis</div>
            <div className="text-[11px] text-[#687386] mt-0.5">AST pattern scanners eliminate hallucinations</div>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-[#36D399] shrink-0 mt-0.5" />
          <div>
            <div className="text-xs font-semibold text-[#F4F7FB]">Grounded AI Reasoning</div>
            <div className="text-[11px] text-[#687386] mt-0.5">Finding tied directly to exact source evidence</div>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-[#36D399] shrink-0 mt-0.5" />
          <div>
            <div className="text-xs font-semibold text-[#F4F7FB]">Safe, Validated Fixes</div>
            <div className="text-[11px] text-[#687386] mt-0.5">5-point patch safety check before code changes</div>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-[#36D399] shrink-0 mt-0.5" />
          <div>
            <div className="text-xs font-semibold text-[#F4F7FB]">Instant Reanalysis</div>
            <div className="text-[11px] text-[#687386] mt-0.5">Verify score improvements & zero regressions</div>
          </div>
        </div>
      </div>
    </div>
  );
}
