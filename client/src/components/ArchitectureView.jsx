import React, { useState } from "react";
import { Network, FileCode, ArrowDown } from "lucide-react";

export default function ArchitectureView({ project, onSelectFile }) {
  const files = project?.files ?? [];
  const findings = project?.findings ?? [];

  // Categorize files dynamically based on actual file paths from project
  const categorized = files.reduce(
    (acc, f) => {
      const path = (f.path || f.filename || f.name || "").toLowerCase();
      if (path.includes("route") || path.includes("api") || path.includes("controller") || path.includes("handler")) {
        acc.routes.push(f);
      } else if (path.includes("service") || path.includes("logic") || path.includes("manager") || path.includes("client")) {
        acc.services.push(f);
      } else if (path.includes("repo") || path.includes("db") || path.includes("database") || path.includes("query") || path.includes("store")) {
        acc.database.push(f);
      } else {
        acc.modules.push(f);
      }
      return acc;
    },
    { routes: [], services: [], database: [], modules: [] }
  );

  const [selectedNode, setSelectedNode] = useState(files[0] || null);

  const getFindingsForFile = (filePath) => {
    if (!filePath) return [];
    return findings.filter((f) => f.file === filePath || f.path === filePath);
  };

  // Grouping list for rendering layers
  const layers = [
    { title: "ENTRY POINTS & HANDLERS", items: categorized.routes.length > 0 ? categorized.routes : categorized.modules.slice(0, Math.ceil(files.length / 3)), color: "text-[#7C8CFF]" },
    { title: "BUSINESS LOGIC & SERVICES", items: categorized.services.length > 0 ? categorized.services : categorized.modules.slice(Math.ceil(files.length / 3), Math.ceil((files.length * 2) / 3)), color: "text-[#F4C95D]" },
    { title: "DATA ACCESS & SINKS", items: categorized.database.length > 0 ? categorized.database : categorized.modules.slice(Math.ceil((files.length * 2) / 3)), color: "text-[#36D399]" },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-6">
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
              Dynamic call path dependency hierarchy derived from repository files
            </p>
          </div>
        </div>
      </div>

      {files.length === 0 ? (
        <div className="cm-card p-12 text-center text-xs text-[#687386] border-[#232936]">
          Import a repository to visualize component dependencies and call paths.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left 8 Cols: Dependency Graph Flow */}
          <div className="lg:col-span-8 space-y-6">
            {layers.map((layer, lIdx) => (
              <React.Fragment key={lIdx}>
                {layer.items.length > 0 && (
                  <div className="space-y-2">
                    <span className={`text-[11px] font-mono uppercase tracking-wider block font-semibold ${layer.color}`}>
                      {layer.title} ({layer.items.length})
                    </span>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {layer.items.map((f, i) => {
                        const filePath = f.path || f.filename || f.name || `file_${i}`;
                        const nodeFindings = getFindingsForFile(filePath);
                        const isSelected = selectedNode === f;
                        return (
                          <div
                            key={i}
                            onClick={() => setSelectedNode(f)}
                            className={`p-3.5 rounded-lg border cursor-pointer transition-all ${
                              isSelected
                                ? "bg-[#151922] border-[#7C8CFF] shadow-lg shadow-[#7C8CFF]/10"
                                : "bg-[#10131A] border-[#232936] hover:border-[#7C8CFF]/40"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2 truncate">
                                <FileCode className={`w-4 h-4 shrink-0 ${layer.color}`} />
                                <span className="text-xs font-mono font-semibold text-[#F4F7FB] truncate">
                                  {filePath}
                                </span>
                              </div>
                              {nodeFindings.length > 0 && (
                                <span className="cm-badge cm-badge-critical shrink-0">
                                  {nodeFindings.length}
                                </span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                {lIdx < layers.length - 1 && layer.items.length > 0 && (
                  <div className="flex justify-center text-[#687386]">
                    <ArrowDown className="w-5 h-5" />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>

          {/* Right 4 Cols: Selected Node Details */}
          <div className="lg:col-span-4 cm-card p-5 border-[#232936] bg-[#10131A] space-y-4">
            <div className="border-b border-[#232936] pb-3">
              <span className="text-xs font-mono text-[#687386] uppercase tracking-wider block">
                COMPONENT METRICS
              </span>
              <h3 className="text-sm font-bold font-mono text-[#F4F7FB] mt-1 truncate">
                {selectedNode?.path || selectedNode?.filename || selectedNode?.name || "Select a Component"}
              </h3>
            </div>

            {selectedNode ? (
              <div className="space-y-4 text-xs font-mono">
                <div className="space-y-1.5">
                  <span className="text-[#687386] block text-[10px]">VERIFIED FINDINGS IN FILE</span>
                  {getFindingsForFile(selectedNode.path || selectedNode.filename || selectedNode.name).length === 0 ? (
                    <p className="text-[#36D399] text-[11px] p-2 rounded bg-[#090B10] border border-[#232936]">
                      ✓ No vulnerabilities detected in file.
                    </p>
                  ) : (
                    getFindingsForFile(selectedNode.path || selectedNode.filename || selectedNode.name).map((f, i) => (
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
