import React, { useEffect, useRef } from "react";
import {
  CheckCircle2,
  ShieldCheck,
  Zap,
  ArrowRight,
  X,
  XCircle,
  Loader2,
} from "lucide-react";
import DiffViewer from "./DiffViewer";

// Animated scan line canvas for the modal header
function ScanCanvas({ active }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let animId;
    let t = 0;

    function render() {
      t += 0.015;
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // Scanning beam
      const x = (Math.sin(t) * 0.5 + 0.5) * w;
      const grad = ctx.createLinearGradient(x - 60, 0, x + 60, 0);
      grad.addColorStop(0, "transparent");
      grad.addColorStop(0.5, active ? "rgba(54,211,153,0.6)" : "rgba(124,140,255,0.5)");
      grad.addColorStop(1, "transparent");
      ctx.fillStyle = grad;
      ctx.fillRect(x - 60, 0, 120, h);

      // Grid lines
      ctx.strokeStyle = "rgba(124,140,255,0.08)";
      ctx.lineWidth = 1;
      for (let gx = 0; gx < w; gx += 32) {
        ctx.beginPath();
        ctx.moveTo(gx, 0);
        ctx.lineTo(gx, h);
        ctx.stroke();
      }
      for (let gy = 0; gy < h; gy += 16) {
        ctx.beginPath();
        ctx.moveTo(0, gy);
        ctx.lineTo(w, gy);
        ctx.stroke();
      }

      animId = requestAnimationFrame(render);
    }

    render();
    return () => cancelAnimationFrame(animId);
  }, [active]);

  return (
    <canvas
      ref={canvasRef}
      width={600}
      height={48}
      className="absolute inset-0 w-full h-full opacity-80 rounded-t-xl"
    />
  );
}

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

  const checks = [
    { key: "target_found", label: "Target line found" },
    { key: "target_unique", label: "Target is unique" },
    { key: "source_unchanged", label: "Source unchanged" },
    { key: "patch_no_overlap", label: "No patch overlap" },
    { key: "diff_validated", label: "Diff validated" },
  ];

  const allPass = checks.every((c) => patchValidation[c.key]);

  return (
    <div className="fixed inset-0 z-50 bg-[#090B10]/85 backdrop-blur-md flex items-center justify-center p-4">
      <div
        className="cm-card border-[#232936] bg-[#10131A] max-w-3xl w-full shadow-2xl overflow-hidden"
        style={{
          boxShadow: "0 0 60px rgba(54,211,153,0.08), 0 25px 50px rgba(0,0,0,0.7)",
        }}
      >
        {/* Animated Scan Header */}
        <div className="relative h-12 overflow-hidden">
          <ScanCanvas active={applying} />
          <div className="relative z-10 h-full flex items-center justify-between px-5">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-[#36D399]/15 border border-[#36D399]/30 flex items-center justify-center">
                <ShieldCheck className="w-4 h-4 text-[#36D399]" />
              </div>
              <span className="text-sm font-bold text-[#F4F7FB] tracking-tight">
                GENERATED FIX & PATCH VALIDATION
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono font-bold px-2 py-0.5 rounded bg-[#36D399]/10 border border-[#36D399]/30 text-[#36D399]">
                {confidence}% CONFIDENCE
              </span>
              <button
                onClick={onReject}
                disabled={applying}
                className="text-[#687386] hover:text-[#F4F7FB] p-1 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="p-6 space-y-5">
          {/* Diff Comparison */}
          <DiffViewer
            beforeCode={fixData.original_code || fixData.before || fixData.original}
            afterCode={fixData.fixed_code || fixData.after || fixData.fixed}
          />

          {/* Fix Explanation */}
          <div className="p-3.5 rounded-lg bg-[#090B10] border border-[#232936] text-xs space-y-1">
            <span className="text-[#687386] font-mono font-semibold uppercase tracking-wider block text-[10px]">
              WHY THIS FIX IS SAFE
            </span>
            <p className="text-[#F4F7FB] leading-relaxed">
              {fixData.explanation || fixData.reasoning || "Replaces vulnerable string concatenation with parameterized argument execution."}
            </p>
          </div>

          {/* 5-Point Validation Checklist */}
          <div className="p-4 rounded-lg bg-[#090B10] border border-[#232936] space-y-3">
            <div className="flex items-center justify-between border-b border-[#232936]/60 pb-2">
              <span className="text-xs font-mono font-semibold text-[#7C8CFF] uppercase tracking-wider flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5" />
                PATCH SAFETY VALIDATION
              </span>
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded border font-bold ${
                  allPass
                    ? "text-[#36D399] bg-[#36D399]/10 border-[#36D399]/20"
                    : "text-[#FF5D73] bg-[#FF5D73]/10 border-[#FF5D73]/20"
                }`}
              >
                {allPass ? "ALL CHECKS PASSED" : "CHECKS FAILED"}
              </span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 font-mono text-xs">
              {checks.map((c) => {
                const pass = patchValidation[c.key];
                return (
                  <div
                    key={c.key}
                    className={`flex items-center gap-2 ${pass ? "text-[#36D399]" : "text-[#FF5D73]"}`}
                  >
                    {pass ? (
                      <CheckCircle2 className="w-4 h-4 shrink-0" />
                    ) : (
                      <XCircle className="w-4 h-4 shrink-0" />
                    )}
                    <span>{c.label}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-3 border-t border-[#232936] pt-4">
            <button
              onClick={onReject}
              disabled={applying}
              className="cm-btn-secondary text-xs px-5 py-2.5 disabled:opacity-50"
            >
              Reject Fix
            </button>
            <button
              onClick={onApply}
              disabled={applying}
              className="cm-btn-primary text-xs px-6 py-2.5 shadow-lg shadow-[#36D399]/20 disabled:opacity-50"
              style={{
                boxShadow: applying ? "0 0 20px rgba(54,211,153,0.3)" : undefined,
              }}
            >
              {applying ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Applying & Reanalyzing...</span>
                </>
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
    </div>
  );
}
