import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, XCircle, MinusCircle, Circle, Loader2, Zap, X, AlertTriangle } from "lucide-react";
import { startFixAll, getFixAllStatus, stopFixAll } from "../api/client";

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };
const SEVERITY_COLOR = {
  critical: "text-[#FF5D73]",
  high: "text-[#FF8A65]",
  medium: "text-[#F4C95D]",
  low: "text-[#36D399]",
};

function sortBySeverity(findings) {
  // Mirrors services/fix_all.py's _sort_queue exactly (severity, then
  // finding_id) so the "in progress" indicator points at the same finding
  // the backend is actually processing, not just a same-severity sibling.
  return [...findings].sort((a, b) => {
    const severityDiff = (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3);
    if (severityDiff !== 0) return severityDiff;
    return (a.finding_id || "").localeCompare(b.finding_id || "");
  });
}

function severityBreakdown(findings) {
  return findings.reduce((acc, f) => {
    acc[f.severity] = (acc[f.severity] || 0) + 1;
    return acc;
  }, {});
}

const STATUS_ICON = {
  fixed: <CheckCircle2 className="w-4 h-4 text-[#36D399]" />,
  failed: <XCircle className="w-4 h-4 text-[#FF5D73]" />,
  skipped: <MinusCircle className="w-4 h-4 text-[#687386]" />,
  already_resolved: <CheckCircle2 className="w-4 h-4 text-[#7C8CFF]" />,
  stale: <MinusCircle className="w-4 h-4 text-[#F4C95D]" />,
  working: <Loader2 className="w-4 h-4 text-[#B98CFF] animate-spin" />,
  waiting: <Circle className="w-4 h-4 text-[#343D50]" />,
};

const STATUS_LABEL = {
  fixed: "Fixed",
  failed: "Failed",
  skipped: "Skipped",
  already_resolved: "Already Resolved",
  stale: "Skipped — Stale Finding",
  working: "Applying safe patch...",
  waiting: "Waiting",
};

export default function FixAllModal({ projectId, findings, onClose, onComplete, onRetryFinding }) {
  // phases: confirm -> running -> done -> error
  const [phase, setPhase] = useState("confirm");
  const [status, setStatus] = useState(null); // raw poll payload
  const [startError, setStartError] = useState(null);
  const pollRef = useRef(null);
  const completedRef = useRef(false);

  const queue = sortBySeverity(findings);
  const breakdown = severityBreakdown(findings);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const beginPolling = () => {
    pollRef.current = setInterval(async () => {
      try {
        const data = await getFixAllStatus(projectId);
        setStatus(data);
        // The job-level status is only ever running/completed/failed; the
        // finer completed-but-verification-failed distinction lives in
        // data.report.status and is handled by the "done" phase's own render.
        if (data.status === "completed" || data.status === "failed") {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setPhase(data.status === "failed" ? "error" : "done");
          if (!completedRef.current) {
            completedRef.current = true;
            onComplete?.();
          }
        }
      } catch (err) {
        // Transient poll failure -- keep polling, the backend job itself is unaffected.
      }
    }, 1200);
  };

  const handleStart = async () => {
    setStartError(null);
    try {
      const data = await startFixAll(projectId);
      setStatus({ status: "running", total: data.total, processed: 0, results: [] });
      setPhase("running");
      beginPolling();
    } catch (err) {
      setStartError(err.message || "Could not start Fix All.");
    }
  };

  const handleStop = async () => {
    try {
      await stopFixAll(projectId);
    } catch {
      // best effort -- the running job will still stop between findings on its own next check
    }
  };

  const resultsByFindingId = new Map((status?.results || []).map((r) => [r.finding_id, r]));
  const processedCount = status?.results?.length ?? 0;

  const report = status?.report;

  return (
    <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-[#232936] bg-[#0D0F14] shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#232936]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#F4C95D]/15 border border-[#F4C95D]/30 flex items-center justify-center text-[#F4C95D]">
              <Zap className="w-4 h-4" />
            </div>
            <span className="text-sm font-bold text-[#F4F7FB] tracking-tight">
              {phase === "confirm" && "Fix All Confirmed Issues?"}
              {phase === "running" && "FIX ALL — Running"}
              {phase === "done" && "FIX ALL COMPLETE"}
              {phase === "error" && "FIX ALL FAILED"}
            </span>
          </div>
          {phase !== "running" && (
            <button onClick={onClose} className="text-[#687386] hover:text-[#F4F7FB] transition-colors">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        <div className="p-5 space-y-4">
          {phase === "confirm" && (
            <>
              <p className="text-sm text-[#C7CDD6] leading-relaxed">
                SAGE will process <span className="font-semibold text-[#F4F7FB]">{queue.length}</span> confirmed
                security findings sequentially using the latest project source.
              </p>
              <div className="flex flex-wrap gap-2">
                {["critical", "high", "medium", "low"].map((sev) =>
                  breakdown[sev] ? (
                    <span key={sev} className={`text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-[#10131A] border border-[#232936] ${SEVERITY_COLOR[sev]}`}>
                      {sev}: {breakdown[sev]}
                    </span>
                  ) : null
                )}
              </div>
              <p className="text-[11px] text-[#4B5565] italic">
                Not every issue is guaranteed to be fixed automatically — each fix is validated before being applied,
                and a final re-analysis confirms what actually resolved.
              </p>
              {startError && (
                <div className="flex items-start gap-2 p-3 rounded-lg border border-[#FF5D73]/30 bg-[#FF5D73]/5 text-xs text-[#FF5D73]">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  {startError}
                </div>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={onClose} className="px-4 py-2 rounded-lg text-xs font-semibold text-[#9AA4B2] hover:text-[#F4F7FB] border border-[#232936] hover:bg-[#10131A] transition-colors">
                  Cancel
                </button>
                <button onClick={handleStart} className="px-4 py-2 rounded-lg text-xs font-semibold bg-[#F4C95D] text-[#090B10] hover:bg-[#F4C95D]/85 transition-colors flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5" /> Fix All
                </button>
              </div>
            </>
          )}

          {(phase === "running" || phase === "done" || phase === "error") && (
            <>
              {phase === "running" && (
                <div className="flex items-center justify-between text-xs text-[#9AA4B2] font-mono">
                  <span>{processedCount} / {queue.length} processed</span>
                  <button onClick={handleStop} className="px-3 py-1.5 rounded-md text-[11px] font-semibold text-[#FF5D73] border border-[#FF5D73]/30 hover:bg-[#FF5D73]/10 transition-colors">
                    Stop Fixing
                  </button>
                </div>
              )}

              {phase === "error" && (
                <div className="flex items-start gap-2 p-3 rounded-lg border border-[#FF5D73]/30 bg-[#FF5D73]/5 text-xs text-[#FF5D73]">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  {status?.error || "Fix All ended unexpectedly."}
                </div>
              )}

              {report && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                  <div className="p-2.5 rounded-lg bg-[#36D399]/10 border border-[#36D399]/25">
                    <div className="text-lg font-bold text-[#36D399]">{report.fixed}</div>
                    <div className="text-[10px] text-[#9AA4B2] font-mono">FIXED</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-[#7C8CFF]/10 border border-[#7C8CFF]/25">
                    <div className="text-lg font-bold text-[#7C8CFF]">{report.already_resolved}</div>
                    <div className="text-[10px] text-[#9AA4B2] font-mono">ALREADY RESOLVED</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-[#FF5D73]/10 border border-[#FF5D73]/25">
                    <div className="text-lg font-bold text-[#FF5D73]">{report.failed}</div>
                    <div className="text-[10px] text-[#9AA4B2] font-mono">FAILED</div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-[#151922] border border-[#232936]">
                    <div className="text-lg font-bold text-[#687386]">{report.skipped}</div>
                    <div className="text-[10px] text-[#9AA4B2] font-mono">SKIPPED</div>
                  </div>
                </div>
              )}

              {report && (
                <div className="flex items-center justify-center gap-3 py-2 text-xs font-mono text-[#9AA4B2]">
                  <span>Before: <span className="text-[#F4F7FB] font-bold">{report.before_count}</span></span>
                  <span className="text-[#4B5565]">→</span>
                  <span>After: <span className="text-[#F4F7FB] font-bold">{report.after_count}</span></span>
                </div>
              )}

              {report?.verification_note && (
                <p className={`text-[11px] text-center italic ${report.status === "completed_verification_failed" ? "text-[#F4C95D]" : "text-[#4B5565]"}`}>
                  {report.verification_note}
                </p>
              )}

              {report?.stopped_early && (
                <p className="text-[11px] text-center text-[#F4C95D]">Run was stopped before processing the full queue.</p>
              )}

              <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1">
                {queue.map((finding, index) => {
                  const result = resultsByFindingId.get(finding.finding_id);
                  const isCurrent = phase === "running" && !result && index === processedCount;
                  const displayStatus = result ? result.status : isCurrent ? "working" : "waiting";
                  return (
                    <div key={finding.finding_id || index} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-[#10131A] border border-[#232936]">
                      {STATUS_ICON[displayStatus] || STATUS_ICON.waiting}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs font-semibold truncate ${SEVERITY_COLOR[finding.severity] || "text-[#F4F7FB]"}`}>
                            {finding.message || finding.rule_id || finding.rule}
                          </span>
                        </div>
                        <div className="text-[10px] text-[#687386] font-mono truncate">{finding.file}</div>
                        <div className="text-[10px] text-[#9AA4B2] mt-0.5">
                          {result?.message || STATUS_LABEL[displayStatus]}
                        </div>
                        {result?.status === "failed" && (
                          <div className="flex gap-2 mt-1.5">
                            <button
                              onClick={() => onRetryFinding?.(finding)}
                              className="text-[10px] font-semibold text-[#7C8CFF] hover:underline"
                            >
                              Retry Individually
                            </button>
                            <button
                              onClick={() => onRetryFinding?.(finding, true)}
                              className="text-[10px] font-semibold text-[#9AA4B2] hover:underline"
                            >
                              Open Finding
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {(phase === "done" || phase === "error") && (
                <div className="flex justify-end pt-2">
                  <button onClick={onClose} className="px-4 py-2 rounded-lg text-xs font-semibold bg-[#151922] text-[#F4F7FB] border border-[#232936] hover:bg-[#1a1f2b] transition-colors">
                    Close
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
