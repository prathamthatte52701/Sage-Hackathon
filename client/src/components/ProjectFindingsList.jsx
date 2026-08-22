import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import ProjectFindingCard from "./ProjectFindingCard";

const SEVERITIES = ["critical", "high", "medium", "low"];
const CATEGORIES = ["security", "best_practice"];

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };

function severityRank(severity) {
  return SEVERITY_ORDER[severity] ?? 4;
}

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

function toggle(set, value) {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export default function ProjectFindingsList({ findings, files, language, projectId }) {
  const [severityFilter, setSeverityFilter] = useState(new Set());
  const [categoryFilter, setCategoryFilter] = useState(new Set());
  const [pathFilter, setPathFilter] = useState("");

  const filtered = useMemo(() => {
    const list = (findings ?? []).filter((f) => {
      if (severityFilter.size > 0 && !severityFilter.has(f?.severity)) return false;
      if (categoryFilter.size > 0 && !categoryFilter.has(f?.category)) return false;
      if (pathFilter.trim() && !f?.file?.toLowerCase().includes(pathFilter.trim().toLowerCase())) return false;
      return true;
    });
    return [...list].sort((a, b) => severityRank(a?.severity) - severityRank(b?.severity));
  }, [findings, severityFilter, categoryFilter, pathFilter]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Severity</span>
          {SEVERITIES.map((sev) => (
            <button
              key={sev}
              type="button"
              onClick={() => setSeverityFilter((s) => toggle(s, sev))}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize transition-colors ${
                severityFilter.has(sev)
                  ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-300"
                  : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
              }`}
            >
              {sev}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Category</span>
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setCategoryFilter((s) => toggle(s, cat))}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                categoryFilter.has(cat)
                  ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-300"
                  : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
              }`}
            >
              {cat === "best_practice" ? "Best Practice" : "Security"}
            </button>
          ))}
        </div>

        <input
          type="text"
          value={pathFilter}
          onChange={(e) => setPathFilter(e.target.value)}
          placeholder="Filter by file path..."
          className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-8 text-center text-sm text-zinc-500">
          No findings match these filters.
        </div>
      ) : (
        <motion.div variants={container} initial="hidden" animate="show" className="flex flex-col gap-4">
          {filtered.map((finding, i) => {
            const fileEntry = (files ?? []).find((f) => f.path === finding?.file);
            const findingIndex = (findings ?? []).indexOf(finding);
            return (
              <ProjectFindingCard
                key={`${finding?.file ?? "x"}-${finding?.line ?? "x"}-${finding?.rule ?? i}-${i}`}
                finding={finding}
                files={files}
                language={fileEntry?.language || language}
                projectId={projectId}
                findingIndex={findingIndex}
              />
            );
          })}
        </motion.div>
      )}
    </div>
  );
}
