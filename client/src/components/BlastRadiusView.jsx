import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bomb,
  Database,
  ExternalLink,
  FileCode,
  GitBranch,
  Loader2,
  Network,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { getBlastRadius } from "../api/client";

const LEVEL_STYLES = {
  low: "border-[#36D399]/35 bg-[#36D399]/10 text-[#36D399]",
  medium: "border-[#F4C95D]/40 bg-[#F4C95D]/10 text-[#F4C95D]",
  high: "border-[#FF9F43]/45 bg-[#FF9F43]/10 text-[#FFB86B]",
  critical: "border-[#FF5D73]/55 bg-[#FF5D73]/12 text-[#FF7B8B]",
};

const LEVEL_DOT = {
  low: "bg-[#36D399]",
  medium: "bg-[#F4C95D]",
  high: "bg-[#FF9F43]",
  critical: "bg-[#FF5D73]",
};

function levelClass(level) {
  return LEVEL_STYLES[level] || LEVEL_STYLES.low;
}

function dotClass(level) {
  return LEVEL_DOT[level] || LEVEL_DOT.low;
}

function compactPath(path = "") {
  const parts = String(path).split("/");
  if (parts.length <= 2) return path;
  return `${parts[0]}/.../${parts[parts.length - 1]}`;
}

function GraphNode({ component, selected, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-[188px] min-h-[92px] rounded-lg border p-3 text-left transition-all ${levelClass(component.level)} ${
        selected ? "shadow-lg shadow-[#7C8CFF]/20 ring-1 ring-[#7C8CFF]" : "hover:border-[#7C8CFF]/60"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <FileCode className="w-4 h-4 shrink-0 mt-0.5" />
        <span className="text-[10px] font-mono font-bold uppercase">{component.level}</span>
      </div>
      <div className="mt-2 text-xs font-mono font-bold text-[#F4F7FB] truncate">
        {component.label || component.id}
      </div>
      <div className="mt-1 text-[10px] font-mono text-[#9AA4B2] truncate">
        {compactPath(component.id)}
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] font-mono">
        <span>{Number(component.score || 0).toFixed(1)} / 10</span>
        <span>{component.direct_dependents || 0} deps</span>
      </div>
    </button>
  );
}

function SummaryTile({ label, value, tone = "text-[#F4F7FB]" }) {
  return (
    <div className="rounded-lg border border-[#232936] bg-[#10131A] p-4">
      <div className="text-[10px] font-mono uppercase tracking-wider text-[#687386]">{label}</div>
      <div className={`mt-2 text-2xl font-mono font-bold ${tone}`}>{value}</div>
    </div>
  );
}

function EmptyState({ projectId }) {
  return (
    <div className="cm-card border-[#232936] bg-[#10131A] p-10 text-center">
      <Network className="mx-auto h-10 w-10 text-[#687386]" />
      <h3 className="mt-4 text-sm font-bold text-[#F4F7FB]">No project selected</h3>
      <p className="mt-2 text-xs text-[#9AA4B2]">
        {projectId ? "No Python components were found for blast-radius analysis." : "Import a Python project to calculate component impact."}
      </p>
    </div>
  );
}

export default function BlastRadiusView({ projectId }) {
  const [report, setReport] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadReport = async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const data = await getBlastRadius(projectId);
      setReport(data);
      setSelectedId((data.components || [])[0]?.id || "");
    } catch (err) {
      setError(err.message || "Blast Radius analysis failed.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setReport(null);
    setSelectedId("");
    loadReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const components = report?.components || [];
  const edges = report?.edges || [];
  const selected = components.find((item) => item.id === selectedId) || components[0] || null;
  const edgeKey = edges.map((edge) => `${edge.source}->${edge.target}:${edge.relation}`).join("|");
  const edgeBySource = useMemo(() => {
    const grouped = new Map();
    for (const edge of edges) {
      if (!grouped.has(edge.source)) grouped.set(edge.source, []);
      grouped.get(edge.source).push(edge);
    }
    return grouped;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edgeKey]);

  if (!projectId) return <EmptyState />;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col gap-4 border-b border-[#232936] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-[#FF5D73]/35 bg-[#FF5D73]/12 text-[#FF5D73]">
            <Bomb className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold tracking-tight text-[#F4F7FB]">BLAST RADIUS</h2>
            <p className="text-xs text-[#9AA4B2]">What breaks if this component fails?</p>
          </div>
        </div>
        <button
          type="button"
          onClick={loadReport}
          disabled={loading}
          className="cm-btn-primary inline-flex items-center justify-center gap-2 px-4 py-2 text-xs disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Recalculate
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-[#FF5D73]/35 bg-[#FF5D73]/10 p-4 text-sm text-[#FF9CAB]">
          {error}
        </div>
      )}

      {loading && !report ? (
        <div className="cm-card border-[#232936] bg-[#10131A] p-10 text-center text-sm text-[#9AA4B2]">
          <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin text-[#7C8CFF]" />
          Calculating deterministic impact graph...
        </div>
      ) : components.length === 0 ? (
        <EmptyState projectId={projectId} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <SummaryTile label="Components analyzed" value={report.summary?.components_analyzed || 0} />
            <SummaryTile label="High-impact components" value={report.summary?.high_blast_components || 0} tone="text-[#FFB86B]" />
            <SummaryTile label="Critical dependency" value={report.summary?.critical_component || "none"} tone="text-[#FF7B8B]" />
          </div>

          {report.ai?.error && (
            <div className="rounded-lg border border-[#F4C95D]/30 bg-[#F4C95D]/10 p-3 text-xs text-[#F4C95D]">
              AI explanation unavailable; deterministic graph and scores are still shown.
            </div>
          )}

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
            <div className="xl:col-span-8 space-y-4">
              <div className="cm-card border-[#232936] bg-[#10131A] p-4">
                <div className="mb-4 flex items-center gap-2 text-[11px] font-mono font-bold uppercase tracking-wider text-[#7C8CFF]">
                  <GitBranch className="h-4 w-4" />
                  Component Dependency Graph ({edges.length} grounded edge{edges.length === 1 ? "" : "s"})
                </div>
                <div className="overflow-x-auto pb-2">
                  <div className="min-w-[760px] space-y-5">
                    {components.slice(0, 12).map((component) => {
                      const outgoing = edgeBySource.get(component.id) || [];
                      return (
                        <div key={component.id} className="flex items-center gap-4">
                          <GraphNode
                            component={component}
                            selected={selected?.id === component.id}
                            onClick={() => setSelectedId(component.id)}
                          />
                          <div className="flex min-h-[92px] flex-1 items-center gap-3 overflow-x-auto">
                            {outgoing.length === 0 ? (
                              <div className="rounded-lg border border-dashed border-[#232936] px-4 py-3 text-[11px] font-mono text-[#687386]">
                                no imported local component
                              </div>
                            ) : (
                              outgoing.map((edge) => {
                                const target = components.find((item) => item.id === edge.target);
                                return (
                                  <React.Fragment key={`${edge.source}-${edge.target}`}>
                                    <ArrowRight className="h-4 w-4 shrink-0 text-[#687386]" />
                                    <button
                                      type="button"
                                      onClick={() => setSelectedId(edge.target)}
                                      className={`rounded-lg border px-3 py-2 text-left text-xs font-mono transition ${levelClass(target?.level || "low")}`}
                                    >
                                      <span className="block max-w-[150px] truncate text-[#F4F7FB]">{target?.label || edge.target}</span>
                                      <span className="text-[10px] text-[#9AA4B2]">imports</span>
                                    </button>
                                  </React.Fragment>
                                );
                              })
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="cm-card border-[#232936] bg-[#10131A] p-4">
                <div className="mb-3 text-[11px] font-mono font-bold uppercase tracking-wider text-[#F4C95D]">
                  Most Critical Components
                </div>
                <div className="space-y-2">
                  {components.slice(0, 5).map((component, index) => (
                    <button
                      key={component.id}
                      type="button"
                      onClick={() => setSelectedId(component.id)}
                      className="flex w-full items-center justify-between gap-3 rounded-lg border border-[#232936] bg-[#090B10] px-3 py-2 text-left hover:border-[#7C8CFF]/45"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="text-xs font-mono text-[#687386]">#{index + 1}</span>
                        <span className={`h-2.5 w-2.5 rounded-full ${dotClass(component.level)}`} />
                        <span className="truncate text-xs font-mono font-bold text-[#F4F7FB]">{component.id}</span>
                      </div>
                      <div className="shrink-0 text-xs font-mono">
                        <span className="text-[#F4F7FB]">{Number(component.score || 0).toFixed(1)}</span>
                        <span className="ml-2 uppercase text-[#9AA4B2]">{component.level}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="xl:col-span-4">
              <div className="cm-card sticky top-6 border-[#232936] bg-[#10131A] p-5 space-y-5">
                {selected ? (
                  <>
                    <div className="border-b border-[#232936] pb-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-mono font-bold text-[#F4F7FB]">{selected.id}</h3>
                          <p className="mt-1 text-[11px] uppercase tracking-wider text-[#687386]">{selected.type}</p>
                        </div>
                        <span className={`rounded border px-2 py-1 text-[10px] font-mono font-bold uppercase ${levelClass(selected.level)}`}>
                          {selected.level}
                        </span>
                      </div>
                      <div className="mt-4 text-3xl font-mono font-bold text-[#F4F7FB]">
                        {Number(selected.score || 0).toFixed(1)}
                        <span className="text-sm text-[#687386]"> / 10</span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                      <Metric label="Direct Dependents" value={selected.direct_dependents || 0} />
                      <Metric label="Downstream Reach" value={selected.downstream_dependents || 0} />
                      <Metric label="Affected Routes" value={(selected.affected_routes || []).length} />
                      <Metric label="Findings" value={selected.confirmed_findings || 0} danger={selected.confirmed_findings > 0} />
                    </div>

                    <div className="space-y-2 text-xs">
                      <PanelTitle icon={ShieldAlert} label="Sensitive Sinks" />
                      <div className="flex flex-wrap gap-2">
                        {(selected.impact_sinks || []).length ? (
                          selected.impact_sinks.map((sink) => (
                            <span key={sink} className="rounded border border-[#232936] bg-[#090B10] px-2 py-1 text-[11px] font-mono text-[#F4C95D]">
                              {sink}
                            </span>
                          ))
                        ) : (
                          <span className="text-[#687386]">No sensitive sinks reached.</span>
                        )}
                      </div>
                    </div>

                    <div className="space-y-2 text-xs">
                      <PanelTitle icon={Network} label="Affected Components" />
                      <div className="max-h-32 space-y-1 overflow-y-auto">
                        {(selected.affected_components || []).length ? (
                          selected.affected_components.map((path) => (
                            <div key={path} className="truncate rounded bg-[#090B10] px-2 py-1 font-mono text-[#9AA4B2]">
                              {path}
                            </div>
                          ))
                        ) : (
                          <span className="text-[#687386]">No dependent components found.</span>
                        )}
                      </div>
                    </div>

                    <div className="space-y-2 text-xs">
                      <PanelTitle icon={ExternalLink} label="Affected Routes" />
                      <div className="space-y-1">
                        {(selected.affected_routes || []).slice(0, 6).map((route, index) => (
                          <div key={`${route.file}-${route.path}-${index}`} className="rounded bg-[#090B10] px-2 py-1 font-mono text-[#9AA4B2]">
                            <span className="text-[#7C8CFF]">{route.method}</span> {route.path}
                          </div>
                        ))}
                        {(selected.affected_routes || []).length === 0 && <span className="text-[#687386]">No API routes connected.</span>}
                      </div>
                    </div>

                    <div className="space-y-2 text-xs">
                      <PanelTitle icon={Database} label="Why this matters" />
                      <p className="leading-relaxed text-[#CDD5E1]">{selected.explanation}</p>
                      <p className="leading-relaxed text-[#9AA4B2]">{selected.engineering_consequences}</p>
                    </div>

                    <div className="space-y-2 text-xs">
                      <PanelTitle icon={AlertTriangle} label="Hardening Priorities" />
                      <div className="space-y-2">
                        {(selected.hardening_priorities || []).map((item, index) => (
                          <div key={index} className="rounded-lg border border-[#232936] bg-[#090B10] p-2 text-[#CDD5E1]">
                            {item}
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-[#687386]">Select a component to inspect blast-radius details.</p>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value, danger = false }) {
  return (
    <div className="rounded-lg border border-[#232936] bg-[#090B10] p-3">
      <div className="text-[10px] uppercase tracking-wider text-[#687386]">{label}</div>
      <div className={`mt-1 text-lg font-bold ${danger ? "text-[#FF5D73]" : "text-[#F4F7FB]"}`}>{value}</div>
    </div>
  );
}

function PanelTitle({ icon: Icon, label }) {
  return (
    <div className="flex items-center gap-2 text-[11px] font-mono font-bold uppercase tracking-wider text-[#7C8CFF]">
      <Icon className="h-4 w-4" />
      {label}
    </div>
  );
}
