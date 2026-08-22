import React, { useEffect, useState } from "react";
import { CheckCircle2, TrendingUp, Download, ArrowRight, X } from "lucide-react";
import { fixedProjectZipUrl } from "../api/client";

// Animated counter that counts up to target
function AnimatedNumber({ target, decimals = 1, delay = 0 }) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    const timeout = setTimeout(() => {
      const start = Date.now();
      const duration = 800;

      function tick() {
        const elapsed = Date.now() - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        setValue(eased * target);
        if (progress < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }, delay);

    return () => clearTimeout(timeout);
  }, [target, delay]);

  return <>{value.toFixed(decimals)}</>;
}

export default function ReanalysisResult({ result, projectId, onClose }) {
  if (!result) return null;

  const before = typeof result.before_score === "number" ? result.before_score : 0;
  const after = typeof result.after_score === "number" ? result.after_score : 0;
  const delta = after - before;

  const resolved = result.resolved_findings ?? [];
  const remaining = result.remaining_findings ?? [];
  const fresh = result.new_findings ?? [];

  return (
    <div className="cm-card border-[#36D399]/40 bg-[#10131A] p-5 space-y-4 max-w-md w-full shadow-2xl"
      style={{ boxShadow: "0 0 40px rgba(54,211,153,0.12), 0 20px 40px rgba(0,0,0,0.6)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#232936] pb-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-[#36D399]" />
          <h3 className="text-sm font-bold text-[#F4F7FB] tracking-tight">
            FIX APPLIED & REANALYZED
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono font-bold px-2 py-0.5 rounded bg-[#36D399]/10 border border-[#36D399]/30 text-[#36D399]">
            VERIFIED
          </span>
          {onClose && (
            <button onClick={onClose} className="text-[#687386] hover:text-[#F4F7FB] p-1 transition-colors">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Health Score Animated Delta */}
      <div className="p-4 rounded-xl bg-[#090B10] border border-[#232936] flex items-center justify-between">
        <div>
          <div className="text-[10px] font-mono text-[#687386] uppercase tracking-wider">
            PROJECT HEALTH SCORE
          </div>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-xl font-bold font-mono text-[#9AA4B2] line-through">
              {before.toFixed(1)}
            </span>
            <ArrowRight className="w-4 h-4 text-[#7C8CFF]" />
            <span className="text-3xl font-bold font-mono text-[#36D399]">
              <AnimatedNumber target={after} delay={200} />
            </span>
            <span className="text-xs text-[#687386]">/100</span>
          </div>
        </div>

        {delta >= 0 ? (
          <div className="flex items-center gap-1.5 text-xs font-mono text-[#36D399] bg-[#36D399]/10 px-3 py-1.5 rounded-lg border border-[#36D399]/20 font-bold">
            <TrendingUp className="w-4 h-4" />
            <span>+{delta.toFixed(1)} pts</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-xs font-mono text-[#FF5D73] bg-[#FF5D73]/10 px-3 py-1.5 rounded-lg border border-[#FF5D73]/20 font-bold">
            <span>{delta.toFixed(1)} pts</span>
          </div>
        )}
      </div>

      {/* Metric Stats */}
      <div className="grid grid-cols-3 gap-3 text-center font-mono text-xs">
        <div className="p-2.5 rounded-lg bg-[#090B10] border border-[#232936]">
          <div className="text-[10px] text-[#687386] uppercase tracking-wider">RESOLVED</div>
          <div className="text-xl font-bold text-[#36D399] mt-0.5">
            <AnimatedNumber target={resolved.length || 1} decimals={0} delay={400} />
          </div>
        </div>
        <div className="p-2.5 rounded-lg bg-[#090B10] border border-[#232936]">
          <div className="text-[10px] text-[#687386] uppercase tracking-wider">REMAINING</div>
          <div className={`text-xl font-bold mt-0.5 ${remaining.length ? "text-[#F4C95D]" : "text-[#36D399]"}`}>
            <AnimatedNumber target={remaining.length} decimals={0} delay={550} />
          </div>
        </div>
        <div className="p-2.5 rounded-lg bg-[#090B10] border border-[#232936]">
          <div className="text-[10px] text-[#687386] uppercase tracking-wider">NEW ISSUES</div>
          <div className={`text-xl font-bold mt-0.5 ${fresh.length ? "text-[#FF5D73]" : "text-[#F4F7FB]"}`}>
            <AnimatedNumber target={fresh.length} decimals={0} delay={700} />
          </div>
        </div>
      </div>

      {/* Download Fixed Project */}
      {projectId && (
        <a
          href={fixedProjectZipUrl(projectId)}
          download
          className="cm-btn-primary w-full justify-center py-2.5 shadow-lg shadow-[#7C8CFF]/15 text-xs"
        >
          <Download className="w-4 h-4" />
          <span>Download Fixed Project (.ZIP)</span>
        </a>
      )}
    </div>
  );
}
