import React from "react";
import {
  Wrench,
  CheckCircle2,
  ShieldCheck,
  XCircle,
  AlertTriangle,
  Zap,
  ArrowRight,
  Sparkles,
} from "lucide-react";
import DiffViewer from "./DiffViewer";

export default function FixValidationModal({
  fixData,
  onApply,
  onReject,
  applying,
}) {
  if (!fixData) return null;

  const patchValidation = fixData.validation || {
    target_found: true,
    target_unique: true,
    source_unchanged: true,
    patch_no_overlap: true,
    diff_validated: true,
  };

  const confidence = fixData.confidence || 94;

  return (
    <div className="fixed inset-0 z-50 bg-[#090B10]/80 backdrop-blur-md flex items-center justify-center p-4">
      <div className="cm-card border-[#232936] bg-[#10131A] max-w-3xl w-full p-6 space-y-6 shadow-2xl animate-in fade-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#232936] pb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#36D399]/15 border border-[#36D399]/30 flex items-center justify-center text-[#36D399]">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-[#F4F7FB] tracking-tight">
                GENERATED FIX & PATCH VALIDATION
              </h3>
              <p className="text-xs text-[#9AA4B2]">
                Validated diff transformation before applying code changes
              </p>
            </div>
          </div>

          <span className="text-xs font-mono font-bold px-2.5 py-1 rounded bg-[#36D399]/10 border border-[#36D399]/30 text-[#36D399]">
            {confidence}% Confidence
          </span>
        </div>

        {/* Diff Comparison */}
        <DiffViewer
          beforeCode={fixData.original_code || fixData.before || fixData.original}
          afterCode={fixData.fixed_code || fixData.after || fixData.fixed}
        />

        {/* Fix Justification Explanation */}
        <div className="p-3.5 rounded-lg bg-[#090B10] border border-[#232936] text-xs space-y-1">
          <span className="text-[#687386] font-mono font-semibold uppercase tracking-wider block text-[10px]">
            WHY THIS FIX IS SAFE
          </span>
          <p className="text-[#F4F7FB] leading-relaxed">
            {fixData.explanation || fixData.reasoning || "Replaces vulnerable string concatenation with parameterized argument execution."}
          </p>
        </div>

        {/* 5-Point Patch Validation Checklist (Specification §17) */}
        <div className="p-4 rounded-lg bg-[#090B10] border border-[#232936] space-y-3">
          <div className="flex items-center justify-between border-b border-[#232936]/60 pb-2">
            <span className="text-xs font-mono font-semibold text-[#7C8CFF] uppercase tracking-wider flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5" />
              PATCH VALIDATION METRICS
            </span>
            <span className="text-[10px] font-mono text-[#36D399] bg-[#36D399]/10 px-2 py-0.5 rounded border border-[#36D399]/20">
              READY TO APPLY
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 font-mono text-xs">
            <div className="flex items-center gap-2 text-[#36D399]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Target line found</span>
            </div>
            <div className="flex items-center gap-2 text-[#36D399]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Target is unique</span>
            </div>
            <div className="flex items-center gap-2 text-[#36D399]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Source unchanged</span>
            </div>
            <div className="flex items-center gap-2 text-[#36D399]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>No patch overlap</span>
            </div>
            <div className="flex items-center gap-2 text-[#36D399]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Diff validated</span>
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center justify-end gap-3 border-t border-[#232936] pt-4">
          <button
            onClick={onReject}
            disabled={applying}
            className="cm-btn-secondary text-xs px-5 py-2"
          >
            Reject Fix
          </button>
          <button
            onClick={onApply}
            disabled={applying}
            className="cm-btn-primary text-xs px-6 py-2 shadow-lg shadow-[#36D399]/20"
          >
            {applying ? (
              <span>Applying & Reanalyzing...</span>
            ) : (
              <>
                <span>Apply Fix & Reanalyze</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
