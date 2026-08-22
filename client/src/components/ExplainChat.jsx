import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { explainIssue } from "../api/client";

// Expandable panel under an IssueCard. Calls /api/explain-bug with the full
// code as context (simplest correct approach - no line-slicing needed for MVP).
export default function ExplainChat({ issue, code, language }) {
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function fetchExplanation() {
    setLoading(true);
    setError(null);
    try {
      const data = await explainIssue(issue, code, language);
      setExplanation(data?.explanation || "No explanation was returned.");
    } catch (err) {
      setError(err.message || "Could not load an explanation.");
    } finally {
      setLoading(false);
    }
  }

  // Fetch once, on expand.
  useEffect(() => {
    fetchExplanation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.2 }}
      className="mt-3 overflow-hidden rounded-md border border-zinc-800 bg-zinc-950/60 p-4"
    >
      {loading && (
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-zinc-600 border-t-indigo-400" />
          Getting a deeper explanation...
        </div>
      )}

      {!loading && error && (
        <div className="flex items-center justify-between gap-3 text-sm text-red-300">
          <span>{error}</span>
          <button
            type="button"
            onClick={fetchExplanation}
            className="shrink-0 rounded border border-red-500/30 px-2 py-1 text-xs text-red-200 transition hover:bg-red-500/10"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && explanation && (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">{explanation}</p>
      )}
    </motion.div>
  );
}
