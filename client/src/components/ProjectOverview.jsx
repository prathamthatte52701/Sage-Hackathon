const CATEGORY_LABELS = {
  security: "Security",
  code_quality: "Code Quality",
  testing: "Testing",
  production_readiness: "Production Readiness",
  architecture: "Architecture",
  api_design: "API Design",
  performance: "Performance",
};

const SEVERITY_STYLES = {
  critical: "text-red-300",
  high: "text-orange-300",
  medium: "text-amber-300",
  low: "text-blue-300",
};

// Simple client-side heuristic - a threshold on the overall score, not a
// deeper judgment. Surfaced with a caption so it doesn't overclaim.
function readiness(score) {
  if (score >= 80) return { label: "Ready", classes: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  if (score >= 60) return { label: "Needs Improvement", classes: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
  return { label: "Not Ready", classes: "border-red-500/30 bg-red-500/10 text-red-300" };
}

function scoreColor(score) {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-red-400";
}

export default function ProjectOverview({ project, score }) {
  const meta = project?.project || {};
  const files = project?.files ?? [];
  const findings = project?.findings ?? [];
  const overall = typeof score?.overall_score === "number" ? score.overall_score : 0;
  const ready = readiness(overall);

  const severityCounts = findings.reduce((acc, f) => {
    const s = f?.severity || "low";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  const categories = Object.entries(score?.categories ?? {});

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 backdrop-blur-sm">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium text-zinc-100">{meta.name || "Project"}</h2>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {meta.projectType && (
              <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-indigo-300">
                {meta.projectType}
              </span>
            )}
            {(meta.languages ?? []).map((lang) => (
              <span key={lang} className="rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 text-zinc-400">
                {lang}
              </span>
            ))}
            {(meta.frameworks ?? []).map((fw) => (
              <span key={fw} className="rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 text-zinc-400">
                {fw}
              </span>
            ))}
          </div>
        </div>

        <div className="text-right">
          <div className={`text-4xl font-semibold tabular-nums ${scoreColor(overall)}`}>
            {overall.toFixed(1)}
          </div>
          <p className="text-xs text-zinc-500">overall score</p>
        </div>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <span className={`rounded-full border px-3 py-1 text-xs font-medium ${ready.classes}`}>
          {ready.label}
        </span>
        <span className="text-xs text-zinc-600">Based on overall compliance score</span>
      </div>

      <div className="mb-5 flex flex-wrap gap-4 text-xs text-zinc-400">
        <span>
          {files.length} file{files.length === 1 ? "" : "s"}
        </span>
        <span>
          {findings.length} finding{findings.length === 1 ? "" : "s"}
        </span>
        {Object.entries(severityCounts).map(([sev, count]) => (
          <span key={sev} className={SEVERITY_STYLES[sev] || "text-zinc-400"}>
            {count} {sev}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {categories.map(([key, cat]) => {
          const isPlaceholder = Boolean(cat?.note);
          return (
            <div
              key={key}
              className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 ${
                isPlaceholder ? "border-dashed border-zinc-700 bg-zinc-900/30" : "border-zinc-800 bg-zinc-900/60"
              }`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-zinc-200">{CATEGORY_LABELS[key] || key}</p>
                <p className="text-xs text-zinc-600">weight {Math.round((cat?.weight ?? 0) * 100)}%</p>
                {isPlaceholder && (
                  <span
                    className="mt-1 inline-block rounded-full border border-zinc-700 bg-zinc-900/60 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-500"
                    title={cat.note}
                  >
                    Not yet assessed
                  </span>
                )}
              </div>
              <span className={`shrink-0 text-lg font-semibold tabular-nums ${isPlaceholder ? "text-zinc-500" : scoreColor(cat?.score ?? 0)}`}>
                {cat?.score ?? "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
