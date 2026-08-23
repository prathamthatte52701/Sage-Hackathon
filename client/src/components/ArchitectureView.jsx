import React, { useState } from "react";
import { Network, FileCode, ArrowRight, GitBranch, ShieldAlert } from "lucide-react";
import { buildArchitectureGraph } from "../utils/architectureGraph";

export default function ArchitectureView({ project }) {
  const graph = buildArchitectureGraph(project);
  const [selectedPath, setSelectedPath] = useState(graph.nodes[0]?.path || "");
  const selectedNode = graph.nodes.find((node) => node.path === selectedPath) || graph.nodes[0] || null;
  const layerColors = {
    entry: "text-[#7C8CFF] border-[#7C8CFF]/40 bg-[#7C8CFF]/10",
    service: "text-[#F4C95D] border-[#F4C95D]/40 bg-[#F4C95D]/10",
    data: "text-[#36D399] border-[#36D399]/40 bg-[#36D399]/10",
    module: "text-[#9AA4B2] border-[#687386]/30 bg-[#151922]",
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Title */}
      <div className="flex items-center justify-between border-b border-[#232936] pb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
            <Network className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#F4F7FB] tracking-tight">
              Architecture & Dependency Graph
            </h2>
            <p className="text-xs text-[#9AA4B2]">
              Grounded Python component graph from source files and import evidence
            </p>
          </div>
        </div>
      </div>

      {graph.nodes.length === 0 ? (
        <div className="cm-card p-12 text-center text-xs text-[#687386] border-[#232936]">
          No Python architecture components found. README, fixture JSON, docs, generated files, and metadata are excluded from the graph.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-8 space-y-5">
            <div className="cm-card border-[#232936] bg-[#10131A] p-4 overflow-x-auto">
              <div className="min-w-[640px] grid grid-cols-4 gap-4 items-start">
                {graph.layers.map((layer, layerIndex) => (
                  <div key={layer.key} className="relative space-y-3">
                    <div className={`text-[10px] font-mono uppercase tracking-wider font-bold px-2 py-1 rounded-md border ${layerColors[layer.key]}`}>
                      {layer.title} ({layer.nodes.length})
                    </div>
                    <div className="space-y-3">
                      {layer.nodes.length === 0 ? (
                        <div className="h-20 rounded-lg border border-dashed border-[#232936] bg-[#090B10]/60 flex items-center justify-center text-[10px] font-mono text-[#4B5565]">
                          0 components
                        </div>
                      ) : (
                        layer.nodes.map((node) => {
                          const incoming = graph.edges.filter((edge) => edge.to === node.path).length;
                          const outgoing = graph.edges.filter((edge) => edge.from === node.path).length;
                          const selected = selectedNode?.path === node.path;
                          return (
                            <button
                              type="button"
                              key={node.path}
                              onClick={() => setSelectedPath(node.path)}
                              className={`w-full text-left p-3 rounded-lg border transition-all ${
                                selected
                                  ? "bg-[#151922] border-[#7C8CFF] shadow-lg shadow-[#7C8CFF]/10"
                                  : "bg-[#090B10] border-[#232936] hover:border-[#7C8CFF]/40"
                              }`}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2 min-w-0">
                                    <FileCode className={`w-4 h-4 shrink-0 ${layerColors[layer.key].split(" ")[0]}`} />
                                    <span className="text-xs font-mono font-bold text-[#F4F7FB] truncate">{node.label}</span>
                                  </div>
                                  <div className="text-[10px] font-mono text-[#687386] truncate mt-1">{node.path}</div>
                                </div>
                                {node.findingCount > 0 && (
                                  <span className="flex items-center gap-1 text-[10px] font-mono font-bold text-[#FF5D73] bg-[#FF5D73]/10 border border-[#FF5D73]/30 rounded px-1.5 py-0.5">
                                    <ShieldAlert className="w-3 h-3" />
                                    {node.findingCount}
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center gap-2 mt-2 text-[10px] font-mono text-[#687386]">
                                <span>{incoming} in</span>
                                <span className="text-[#343D50]">/</span>
                                <span>{outgoing} out</span>
                                {node.highestSeverity && <span className="text-[#F4C95D] uppercase">{node.highestSeverity}</span>}
                              </div>
                            </button>
                          );
                        })
                      )}
                    </div>
                    {layerIndex < graph.layers.length - 1 && (
                      <div className="hidden xl:block absolute top-11 -right-3 text-[#343D50]">
                        <ArrowRight className="w-5 h-5" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="cm-card border-[#232936] bg-[#10131A] p-4 space-y-3">
              <div className="flex items-center gap-2 text-[11px] font-mono font-bold text-[#7C8CFF] uppercase tracking-wider">
                <GitBranch className="w-4 h-4" />
                Grounded Dependencies ({graph.edges.length})
              </div>
              {graph.edges.length === 0 ? (
                <p className="text-xs text-[#687386]">No Python import edges were found. CODE MASTER AI is showing valid nodes without invented dependencies.</p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {graph.edges.map((edge, index) => (
                    <div key={`${edge.from}-${edge.to}-${index}`} className="flex items-center gap-2 rounded-lg border border-[#232936] bg-[#090B10] px-3 py-2 text-xs font-mono">
                      <span className="truncate text-[#F4F7FB]">{edge.from}</span>
                      <ArrowRight className="w-3.5 h-3.5 shrink-0 text-[#7C8CFF]" />
                      <span className="truncate text-[#36D399]">{edge.to}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right 4 Cols: Selected Node Details */}
          <div className="lg:col-span-4 cm-card p-5 border-[#232936] bg-[#10131A] space-y-4">
            <div className="border-b border-[#232936] pb-3">
              <span className="text-xs font-mono text-[#687386] uppercase tracking-wider block">
                COMPONENT METRICS
              </span>
              <h3 className="text-sm font-bold font-mono text-[#F4F7FB] mt-1 truncate">
                {selectedNode?.path || "Select a Component"}
              </h3>
            </div>

            {selectedNode ? (
              <div className="space-y-4 text-xs font-mono">
                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2 rounded bg-[#090B10] border border-[#232936]">
                    <span className="block text-[10px] text-[#687386]">KIND</span>
                    <span className="text-[#F4F7FB] uppercase">{selectedNode.kind}</span>
                  </div>
                  <div className="p-2 rounded bg-[#090B10] border border-[#232936]">
                    <span className="block text-[10px] text-[#687386]">FINDINGS</span>
                    <span className={selectedNode.findingCount ? "text-[#FF5D73]" : "text-[#36D399]"}>{selectedNode.findingCount}</span>
                  </div>
                </div>
                <div className="space-y-1 text-[11px] text-[#9AA4B2]">
                  {selectedNode.routes.length > 0 && <div>Routes: <span className="text-[#F4F7FB]">{selectedNode.routes.join(", ")}</span></div>}
                  {selectedNode.functions.length > 0 && <div>Functions: <span className="text-[#F4F7FB]">{selectedNode.functions.slice(0, 6).join(", ")}</span></div>}
                  {selectedNode.classes.length > 0 && <div>Classes: <span className="text-[#F4F7FB]">{selectedNode.classes.slice(0, 6).join(", ")}</span></div>}
                </div>
                <div className="space-y-1.5">
                  <span className="text-[#687386] block text-[10px]">VERIFIED FINDINGS IN FILE</span>
                  {selectedNode.findings.length === 0 ? (
                    <p className="text-[#36D399] text-[11px] p-2 rounded bg-[#090B10] border border-[#232936]">
                      No vulnerabilities detected in file.
                    </p>
                  ) : (
                    selectedNode.findings.map((f, i) => (
                      <div key={i} className="p-2 rounded bg-[#090B10] border border-[#232936] text-[#FF5D73] space-y-1">
                        <div className="font-semibold text-[#F4F7FB]">Line {f.line || 1}: {f.title || f.type || f.rule}</div>
                        <div className="text-[10px] text-[#9AA4B2]">{f.description || f.message}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ) : (
              <p className="text-xs text-[#687386]">Click any architectural component node to inspect file findings.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
