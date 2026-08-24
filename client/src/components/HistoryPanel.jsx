import React from "react";
import { History, FileCode2 } from "lucide-react";

const SEVERITY_DOT = {
  critical: "bg-[#FF5D73]",
  high: "bg-[#F4C95D]",
  medium: "bg-[#57B8FF]",
  low: "bg-[#9AA4B2]",
};

function countBySeverity(issues) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const issue of issues || []) {
    const severity = (issue.severity || "").toLowerCase();
    if (counts[severity] !== undefined) counts[severity] += 1;
  }
  return counts;
}

export default function HistoryPanel({ history = [] }) {
  const items = Array.isArray(history) ? history : [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 border-b border-[#232936] pb-4">
        <div className="w-10 h-10 rounded-xl bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
          <History className="w-5 h-5" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-[#F4F7FB] tracking-tight">Review History</h2>
          <p className="text-xs text-[#9AA4B2]">Recent reviews from this session.</p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="cm-card p-8 border-[#232936] bg-[#10131A] text-center space-y-2">
          <p className="text-sm font-semibold text-[#F4F7FB]">No review history yet.</p>
          <p className="text-xs text-[#9AA4B2]">
            Import a project or run a snippet review to create a history entry.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item, idx) => {
            const findings = item.issues || item.security_findings || item.findings || [];
            const counts = countBySeverity(findings);
            const total = counts.critical + counts.high + counts.medium + counts.low;
            const title = item.project_name || item.language || item.repo_name || "Review";

            return (
              <div key={item._id || item.id || idx} className="cm-card p-4 border-[#232936] bg-[#10131A] space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileCode2 className="w-4 h-4 text-[#7C8CFF] shrink-0" />
                    <span className="text-sm font-semibold text-[#F4F7FB] truncate">{title}</span>
                  </div>
                  <span className="text-[11px] font-mono text-[#687386]">
                    {item.created_at ? new Date(item.created_at).toLocaleString() : "Current session"}
                  </span>
                </div>

                {item.code_snippet && (
                  <pre className="max-h-20 overflow-hidden whitespace-pre-wrap break-all rounded-lg border border-[#232936] bg-[#090B10] p-3 text-xs text-[#9AA4B2]">
                    {item.code_snippet}
                  </pre>
                )}

                <div className="flex flex-wrap items-center gap-3 text-xs text-[#9AA4B2]">
                  {Object.entries(counts).map(
                    ([severity, count]) =>
                      count > 0 && (
                        <span key={severity} className="flex items-center gap-1.5 font-mono">
                          <span className={`h-1.5 w-1.5 rounded-full ${SEVERITY_DOT[severity]}`} />
                          {count} {severity}
                        </span>
                      )
                  )}
                  {total === 0 && <span className="text-[#36D399]">No issues recorded</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
