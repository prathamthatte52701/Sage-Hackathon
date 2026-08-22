import React, { useState } from "react";
import { Skull, Crosshair, ShieldQuestion, FlaskConical, Wrench, AlertTriangle, RefreshCw, FileCode2, Loader2 } from "lucide-react";
import { runHackerLens } from "../api/client";

const RISK_STYLE = {
  critical: { text: "text-[#FF5D73]", bg: "bg-[#FF5D73]/10", border: "border-[#FF5D73]/30" },
  high: { text: "text-[#FF8A65]", bg: "bg-[#FF8A65]/10", border: "border-[#FF8A65]/30" },
  medium: { text: "text-[#F4C95D]", bg: "bg-[#F4C95D]/10", border: "border-[#F4C95D]/30" },
  low: { text: "text-[#36D399]", bg: "bg-[#36D399]/10", border: "border-[#36D399]/30" },
};

function riskStyle(risk) {
  return RISK_STYLE[risk] || RISK_STYLE.low;
}

function EvidenceChips({ evidence }) {
  if (!evidence || evidence.length === 0) {
    return <span className="text-[10px] text-[#4B5565] italic">No confirmed evidence reference</span>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {evidence.map((e, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#0D0F14] border border-[#232936] text-[#9AA4B2]"
        >
          <FileCode2 className="w-2.5 h-2.5 text-[#B98CFF]" />
          {e.file}
          {e.line ? `:${e.line}` : ""}
          {e.function ? ` · ${e.function}()` : ""}
          {e.route ? ` · ${e.route}` : ""}
        </span>
      ))}
    </div>
  );
}

function ObservationCard({ observation, hypothesis = false }) {
  const style = riskStyle(observation.risk);
  return (
    <div className={`p-4 rounded-xl border ${style.border} bg-[#10131A] space-y-2.5`}>
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-sm font-semibold text-[#F4F7FB]">{observation.title}</h4>
        <span className={`shrink-0 text-[10px] font-mono font-bold uppercase px-2 py-0.5 rounded ${style.bg} ${style.text} border ${style.border}`}>
          {observation.risk}
        </span>
      </div>
      {hypothesis && (
        <div className="flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase text-[#B98CFF]">
          <ShieldQuestion className="w-3 h-3" />
          Hacker Hypothesis · Needs Verification
        </div>
      )}
      {observation.reason && <p className="text-xs text-[#9AA4B2] leading-relaxed">{observation.reason}</p>}
      <EvidenceChips evidence={observation.evidence} />
      {observation.potential_impact && (
        <div className="text-xs">
          <span className="text-[#687386] font-medium">Potential impact: </span>
          <span className="text-[#C7CDD6]">{observation.potential_impact}</span>
        </div>
      )}
      {observation.hardening_action && (
        <div className="text-xs flex items-start gap-1.5 pt-1 border-t border-[#232936]">
          <Wrench className="w-3 h-3 text-[#36D399] mt-0.5 shrink-0" />
          <span className="text-[#C7CDD6]">{observation.hardening_action}</span>
        </div>
      )}
    </div>
  );
}

export default function HackerLens({ projectId }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await runHackerLens(projectId);
      setReport(data);
      if (data?.error) setError(data.summary || "Hacker Mode analysis could not complete.");
    } catch (err) {
      setError(err.message || "Hacker Mode analysis failed. Please retry.");
    } finally {
      setLoading(false);
    }
  };

  if (!projectId) {
    return (
      <div className="max-w-5xl mx-auto p-12 text-center text-xs text-[#687386] border border-[#232936] rounded-xl bg-[#10131A]">
        Import a repository first to unlock Hacker Mode.
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-[#232936] pb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#B98CFF]/15 border border-[#B98CFF]/30 flex items-center justify-center text-[#B98CFF]">
            <Skull className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#F4F7FB] tracking-tight flex items-center gap-2">
              👾 Hacker Mode
            </h2>
            <p className="text-xs text-[#9AA4B2]">
              Independent adversarial AI reasoning — where would an attacker focus first?
            </p>
          </div>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold bg-[#B98CFF]/15 border border-[#B98CFF]/40 text-[#B98CFF] hover:bg-[#B98CFF]/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {report ? "Re-run Analysis" : "Run Hacker Mode Analysis"}
        </button>
      </div>

      {!report && !loading && !error && (
        <div className="p-12 text-center text-xs text-[#687386] border border-[#232936] rounded-xl bg-[#10131A] space-y-2">
          <Skull className="w-8 h-8 text-[#343D50] mx-auto" />
          <p>No Hacker Mode analysis has been run yet for this project.</p>
          <p className="text-[#4B5565]">This is independent AI reasoning — it does not use RAG and never touches your Findings.</p>
        </div>
      )}

      {loading && (
        <div className="p-12 text-center text-xs text-[#9AA4B2] border border-[#232936] rounded-xl bg-[#10131A] flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-[#B98CFF] animate-spin" />
          Reasoning about the attack surface...
        </div>
      )}

      {error && !loading && (
        <div className="p-5 rounded-xl border border-[#FF5D73]/30 bg-[#FF5D73]/5 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-[#FF5D73] shrink-0 mt-0.5" />
          <div className="flex-1 space-y-2">
            <p className="text-xs text-[#F4F7FB]">{error}</p>
            <button
              onClick={run}
              className="text-xs font-semibold text-[#FF5D73] hover:underline"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {report && !report.error && (
        <div className="space-y-6">
          {/* Summary + Score */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 p-5 rounded-xl border border-[#232936] bg-[#10131A] space-y-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold">Hacker Summary</span>
              <p className="text-sm text-[#C7CDD6] leading-relaxed">{report.summary}</p>
            </div>
            <div className={`p-5 rounded-xl border ${riskStyle(report.attack_surface_label).border} ${riskStyle(report.attack_surface_label).bg} flex flex-col justify-center items-center text-center space-y-1`}>
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#9AA4B2] font-semibold">Attack Surface</span>
              <span className={`text-[10px] font-mono font-bold uppercase ${riskStyle(report.attack_surface_label).text}`}>
                {report.attack_surface_label}
              </span>
              <span className="text-3xl font-bold text-[#F4F7FB]">
                {report.attack_surface_score.toFixed(1)}<span className="text-sm text-[#687386]"> / 10</span>
              </span>
              {report.score_reasoning && (
                <p className="text-[10px] text-[#687386] leading-snug pt-1">{report.score_reasoning}</p>
              )}
            </div>
          </div>

          {/* Top Targets */}
          {report.top_targets?.length > 0 && (
            <div className="space-y-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
                <Crosshair className="w-3.5 h-3.5" /> Top Targets
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {report.top_targets.map((t) => (
                  <div key={t.rank} className="p-3.5 rounded-lg border border-[#232936] bg-[#10131A] space-y-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-bold text-[#B98CFF]">#{t.rank}</span>
                      <span className="text-sm font-semibold text-[#F4F7FB]">{t.title}</span>
                    </div>
                    {t.reason && <p className="text-xs text-[#9AA4B2]">{t.reason}</p>}
                    <EvidenceChips evidence={t.evidence} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Attack Surfaces */}
          {report.attack_surfaces?.length > 0 && (
            <div className="space-y-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold">Attack Surfaces</span>
              <div className="flex flex-wrap gap-2">
                {report.attack_surfaces.map((s, i) => (
                  <span key={i} className="text-xs font-medium px-2.5 py-1 rounded-full bg-[#151922] border border-[#232936] text-[#C7CDD6]">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Risk Paths */}
          {report.risk_paths?.length > 0 && (
            <div className="space-y-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold">Potential Risk Paths</span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {report.risk_paths.map((path, i) => (
                  <div key={i} className="p-4 rounded-lg border border-[#232936] bg-[#10131A] space-y-2">
                    <div className="text-xs font-semibold text-[#F4F7FB]">{path.label}</div>
                    <div className="flex flex-col">
                      {path.steps.map((step, si) => (
                        <React.Fragment key={si}>
                          <span className="text-xs font-mono text-[#C7CDD6] px-2 py-1 rounded bg-[#0D0F14] border border-[#232936]">
                            {step}
                          </span>
                          {si < path.steps.length - 1 && (
                            <span className="text-[#4B5565] text-xs pl-3 py-0.5">↓</span>
                          )}
                        </React.Fragment>
                      ))}
                    </div>
                    <EvidenceChips evidence={path.evidence} />
                    <p className="text-[10px] text-[#4B5565] italic">Potential risk path, not a guaranteed exploit.</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Adversarial Observations */}
          {report.adversarial_observations?.length > 0 && (
            <div className="space-y-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold">Adversarial Observations</span>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {report.adversarial_observations.map((o, i) => (
                  <ObservationCard key={i} observation={o} />
                ))}
              </div>
            </div>
          )}

          {/* Hacker Hypotheses */}
          {report.hacker_hypotheses?.length > 0 && (
            <div className="space-y-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#687386] font-semibold flex items-center gap-1.5">
                <FlaskConical className="w-3.5 h-3.5" /> Hacker Hypotheses
              </span>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {report.hacker_hypotheses.map((o, i) => (
                  <ObservationCard key={i} observation={o} hypothesis />
                ))}
              </div>
            </div>
          )}

          {/* Hardening Priorities */}
          {report.hardening_priorities?.length > 0 && (
            <div className="p-5 rounded-xl border border-[#36D399]/25 bg-[#36D399]/5 space-y-2.5">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#36D399] font-semibold flex items-center gap-1.5">
                <Wrench className="w-3.5 h-3.5" /> Hardening Priorities
              </span>
              <ol className="space-y-1.5">
                {report.hardening_priorities.map((p, i) => (
                  <li key={i} className="text-xs text-[#C7CDD6] flex gap-2">
                    <span className="font-mono font-bold text-[#36D399] shrink-0">{i + 1}.</span>
                    {p}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {report.files_analyzed?.length > 0 && (
            <p className="text-[10px] text-[#4B5565] pt-2 border-t border-[#232936]">
              Analyzed {report.files_analyzed.length} file(s) from this repository. Hacker Mode uses independent AI
              reasoning only — no RAG/knowledge retrieval, no changes to your Findings.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
