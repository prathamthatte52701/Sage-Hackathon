import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { explainIssue } from "../api/client";

const SEVERITY_STYLES = {
  critical: "bg-red-500/15 text-red-300 border-red-500/30",
  high: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  low: "bg-blue-500/15 text-blue-300 border-blue-500/30",
};

const CATEGORY_LABELS = {
  security: "Security",
  best_practice: "Best Practice",
};

function severityStyle(severity) {
  return SEVERITY_STYLES[severity] || "bg-zinc-500/15 text-zinc-300 border-zinc-500/30";
}

function categoryLabel(category) {
  return CATEGORY_LABELS[category] || category || "General";
}

// Looks up the file containing a finding, for code_context. Falls back to the
// finding's own evidence snippet when file content isn't available, so the
// explain call never goes out with empty context.
function resolveCodeContext(finding, files) {
  const file = (files ?? []).find((f) => f.path === finding.file);
  if (file?.content) return file.content;
  return finding.evidence || "";
}

export default function ProjectFindingCard({ finding, files, language }) {
  const [expanded, setExpanded] = useState(false);
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [fetched, setFetched] = useState(false);

  const severity = finding?.severity || "low";

  async function fetchExplanation() {
    setLoading(true);
    setError(null);
    try {
      const issue = {
        category: finding.category,
        severity: finding.severity,
        line: finding.line,
        issue: finding.message,
        fix_suggestion: "",
      };
      const codeContext = resolveCodeContext(finding, files);
      const data = await explainIssue(issue, codeContext, language);
      setExplanation(data?.explanation || "No explanation was returned.");
    } catch (err) {
      setError(err.message || "Could not load an explanation.");
    } finally {
      setLoading(false);
      setFetched(true);
    }
  }

  function toggleExpand() {
    const next = !expanded;
    setExpanded(next);
    if (next && !fetched) fetchExplanation();
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 shadow-sm shadow-black/20"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${severityStyle(severity)}`}
        >
          {severity}
        </span>
        <span className="rounded-full border border-zinc-700 px-2.5 py-0.5 text-xs text-zinc-400">
          {categoryLabel(finding?.category)}
        </span>
        {finding?.rule && (
          <span className="rounded-full border border-zinc-800 px-2.5 py-0.5 text-xs text-zinc-500">
            {finding.rule}
          </span>
        )}
        <span className="font-mono text-xs text-zinc-500 truncate max-w-full">
          {finding?.file}
          {Number.isFinite(finding?.line) ? `:${finding.line}` : ""}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-zinc-200">
        {finding?.message || "No description provided."}
      </p>

      {finding?.evidence && (
        <pre className="mt-3 overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2.5 text-xs text-zinc-400">
          <code>{finding.evidence}</code>
        </pre>
      )}

      <button
        type="button"
        onClick={toggleExpand}
        className="mt-4 text-xs font-medium text-indigo-400 transition hover:text-indigo-300"
      >
        {expanded ? "Hide explanation ▲" : "Explain this finding ▾"}
      </button>

      <AnimatePresence>
        {expanded && (
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
        )}
      </AnimatePresence>
    </motion.div>
  );
}
