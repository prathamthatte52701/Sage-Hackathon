// Renders the response of POST /reanalyze: a before/after static-analysis
// score comparison. `behavior_verified` is always false from the backend
// (it never runs code) — this component must never imply "verified" or
// "confirmed correct" anywhere, only "here's what static analysis found."

function scoreColor(score) {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-red-400";
}

function deltaTone(before, after) {
  if (after > before) return { arrow: "↑", classes: "text-emerald-400" };
  if (after < before) return { arrow: "↓", classes: "text-red-400" };
  return { arrow: "→", classes: "text-zinc-400" };
}

function FindingRow({ finding }) {
  return (
    <li className="flex flex-wrap items-baseline gap-2 text-xs text-zinc-400">
      <span className="font-mono text-zinc-500">
        {finding.file}
        {Number.isFinite(finding.line) ? `:${finding.line}` : ""}
      </span>
      {finding.rule && <span className="text-zinc-500">{finding.rule}</span>}
      {finding.message && <span className="truncate text-zinc-500">— {finding.message}</span>}
    </li>
  );
}

export default function ReanalysisResult({ result }) {
  if (!result) return null;

  const before = typeof result.before_score === "number" ? result.before_score : 0;
  const after = typeof result.after_score === "number" ? result.after_score : 0;
  const delta = deltaTone(before, after);

  const resolved = result.resolved_findings ?? [];
  const remaining = result.remaining_findings ?? [];
  const fresh = result.new_findings ?? [];

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Static analysis comparison
        </p>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={`text-2xl font-semibold tabular-nums ${scoreColor(before)}`}>
            {before.toFixed(1)}
          </span>
          <span className={`text-lg ${delta.classes}`}>{delta.arrow}</span>
          <span className={`text-2xl font-semibold tabular-nums ${scoreColor(after)}`}>
            {after.toFixed(1)}
          </span>
        </div>
      </div>

      {result.verification_note && (
        <p className="flex gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs leading-relaxed text-blue-300">
          <span className="shrink-0 font-semibold">ℹ</span>
          <span>{result.verification_note}</span>
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs text-emerald-300">
          {resolved.length} resolved
        </span>
        <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs text-amber-300">
          {remaining.length} remaining
        </span>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs ${
            fresh.length > 0
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : "border-zinc-700 bg-zinc-900/60 text-zinc-400"
          }`}
        >
          {fresh.length} new
        </span>
      </div>

      {resolved.length > 0 && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Resolved</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {resolved.map((f, i) => (
              <FindingRow key={`resolved-${i}`} finding={f} />
            ))}
          </ul>
        </div>
      )}

      {fresh.length > 0 && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-red-400">
            New findings introduced
          </p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {fresh.map((f, i) => (
              <FindingRow key={`new-${i}`} finding={f} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
