import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { getHistory } from "../api/client";

const SEVERITY_DOT = {
  critical: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-blue-500",
};

function countBySeverity(issues) {
  const counts = { critical: 0, medium: 0, low: 0 };
  for (const issue of issues || []) {
    if (counts[issue.severity] !== undefined) counts[issue.severity] += 1;
  }
  return counts;
}

export default function HistoryPanel({ sessionId, open, onClose }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getHistory(sessionId)
      .then((data) => {
        if (!cancelled) setItems(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not load history.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, sessionId]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed right-0 top-0 z-50 h-full w-full max-w-sm overflow-y-auto border-l border-zinc-800 bg-zinc-950 p-6"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.25, ease: "easeOut" }}
          >
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-lg font-medium text-zinc-100">Review History</h2>
              <button
                onClick={onClose}
                className="rounded-md px-2 py-1 text-sm text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300"
              >
                Close
              </button>
            </div>

            {loading && <p className="text-sm text-zinc-500">Loading...</p>}
            {error && <p className="text-sm text-red-400">{error}</p>}
            {!loading && !error && items.length === 0 && (
              <p className="text-sm text-zinc-600">No reviews yet in this session.</p>
            )}

            <div className="space-y-3">
              {items.map((item) => {
                const counts = countBySeverity(item.issues);
                return (
                  <div
                    key={item._id}
                    className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3"
                  >
                    <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
                      <span className="uppercase tracking-wide">{item.language}</span>
                      <span>
                        {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
                      </span>
                    </div>
                    <pre className="mb-2 max-h-20 overflow-hidden text-ellipsis whitespace-pre-wrap break-all text-xs text-zinc-400">
                      {item.code_snippet}
                    </pre>
                    <div className="flex items-center gap-3 text-xs text-zinc-400">
                      {Object.entries(counts).map(
                        ([severity, count]) =>
                          count > 0 && (
                            <span key={severity} className="flex items-center gap-1">
                              <span
                                className={`h-1.5 w-1.5 rounded-full ${SEVERITY_DOT[severity]}`}
                              />
                              {count} {severity}
                            </span>
                          )
                      )}
                      {counts.critical + counts.medium + counts.low === 0 && (
                        <span>{item.summary || "No significant issues found"}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
