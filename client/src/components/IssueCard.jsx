import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import ExplainChat from "./ExplainChat";

const SEVERITY_STYLES = {
  critical: "bg-red-500/15 text-red-300 border-red-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  low: "bg-blue-500/15 text-blue-300 border-blue-500/30",
};

const CATEGORY_LABELS = {
  security: "Security",
  logic: "Logic",
  performance: "Performance",
  style: "Style",
  best_practice: "Best Practice",
};

function severityStyle(severity) {
  return SEVERITY_STYLES[severity] || "bg-zinc-500/15 text-zinc-300 border-zinc-500/30";
}

function categoryLabel(category) {
  return CATEGORY_LABELS[category] || category || "General";
}

export default function IssueCard({ issue, code, language }) {
  const [expanded, setExpanded] = useState(false);

  const line = Number.isFinite(issue?.line) ? issue.line : null;
  const severity = issue?.severity || "low";
  const confidence = typeof issue?.confidence === "number" ? issue.confidence : 0;
  const confidencePct = Math.round(Math.min(Math.max(confidence, 0), 1) * 100);

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
          {categoryLabel(issue?.category)}
        </span>
        {line !== null && (
          <span className="font-mono text-xs text-zinc-500">Line {line}</span>
        )}
        {issue?.needs_human_review && (
          <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2.5 py-0.5 text-xs font-medium text-orange-300">
            ⚠ Needs human review
          </span>
        )}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-zinc-200">
        {issue?.issue || "No description provided."}
      </p>

      <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2.5">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Suggested fix</p>
        <p className="mt-1 text-sm text-zinc-300">
          {issue?.fix_suggestion || "No specific suggestion available"}
        </p>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <span className="text-xs text-zinc-500">Confidence</span>
        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-zinc-800">
          <div
            className="h-full rounded-full bg-indigo-500"
            style={{ width: `${confidencePct}%` }}
          />
        </div>
        <span className="font-mono text-xs text-zinc-400">{confidencePct}%</span>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mt-4 text-xs font-medium text-indigo-400 transition hover:text-indigo-300"
      >
        {expanded ? "Hide explanation ▲" : "Explain more ▾"}
      </button>

      <AnimatePresence>
        {expanded && <ExplainChat issue={issue} code={code} language={language} />}
      </AnimatePresence>
    </motion.div>
  );
}
