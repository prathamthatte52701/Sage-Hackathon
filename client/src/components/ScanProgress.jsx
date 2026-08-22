import React from "react";
import { CheckCircle2, Loader2, XCircle, Circle } from "lucide-react";

// Stage mapping to detailed evidence-first steps (Specification §9 & §21)
const STAGES = [
  { key: "reading", label: "Repository imported & files indexed" },
  { key: "indexing", label: "Dependency graph & call paths built" },
  { key: "deterministic", label: "Deterministic AST scanner running" },
  { key: "analyzing", label: "AI quality & security review" },
  { key: "grounding", label: "Grounding findings in source evidence" },
  { key: "scoring", label: "Calculating project health score" },
];

function getStatus(itemKey, currentStage, errorStage) {
  if (itemKey === errorStage) return "error";
  const order = ["reading", "indexing", "deterministic", "analyzing", "grounding", "scoring", "done"];
  const currentIdx = order.indexOf(currentStage);
  const itemIdx = order.indexOf(itemKey);
  if (itemIdx < currentIdx) return "done";
  if (itemIdx === currentIdx) return "active";
  return "pending";
}

export default function ScanProgress({ stage, errorStage }) {
  return (
    <div className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-4 max-w-lg mx-auto shadow-2xl">
      <div className="flex items-center justify-between border-b border-[#232936] pb-3">
        <h3 className="text-sm font-semibold text-[#F4F7FB] flex items-center gap-2">
          <Loader2 className="w-4 h-4 text-[#7C8CFF] animate-spin" />
          <span>ANALYZING CODEBASE</span>
        </h3>
        <span className="text-[11px] font-mono text-[#7C8CFF] bg-[#7C8CFF]/10 px-2 py-0.5 rounded border border-[#7C8CFF]/20">
          REAL-TIME SCANS
        </span>
      </div>

      <div className="space-y-3 font-mono text-xs">
        {STAGES.map((s) => {
          const status = getStatus(s.key, stage, errorStage);
          return (
            <div key={s.key} className="flex items-center gap-3">
              {status === "done" && (
                <CheckCircle2 className="w-4 h-4 text-[#36D399] shrink-0" />
              )}
              {status === "active" && (
                <Loader2 className="w-4 h-4 text-[#7C8CFF] animate-spin shrink-0" />
              )}
              {status === "error" && (
                <XCircle className="w-4 h-4 text-[#FF5D73] shrink-0" />
              )}
              {status === "pending" && (
                <Circle className="w-4 h-4 text-[#687386]/40 shrink-0" />
              )}

              <span
                className={`transition-colors ${
                  status === "done"
                    ? "text-[#F4F7FB]"
                    : status === "active"
                    ? "text-[#7C8CFF] font-semibold"
                    : status === "error"
                    ? "text-[#FF5D73]"
                    : "text-[#687386]"
                }`}
              >
                {s.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
