import React, { useState } from "react";
import { Network, FileCode, ArrowDown, ShieldAlert, CheckCircle2, ChevronRight, Layers } from "lucide-react";

export default function ArchitectureView({ project, onSelectFile }) {
  const files = project?.files ?? [];
  const findings = project?.findings ?? [];

  // Group files into architectural layers (Routes, Services, Repositories/Models, Database/Utils)
  const categorized = files.reduce(
    (acc, f) => {
      const path = (f.path || f.filename || "").toLowerCase();
      if (path.includes("route") || path.includes("api") || path.includes("controller")) {
        acc.routes.push(f);
      } else if (path.includes("service") || path.includes("logic") || path.includes("manager")) {
        acc.services.push(f);
      } else if (path.includes("repo") || path.includes("db") || path.includes("database") || path.includes("query")) {
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
    return findings.filter((f) => f.file === filePath || f.path === filePath);
  };

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
              Visual component hierarchy and call path dependency flow
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left 8 Cols: Dependency Graph Flow (Specification §20) */}
        <div className="lg:col-span-8 space-y-6">
          {/* Layer 1: API / Routes */}
          <div className="space-y-2">
            <span className="text-[11px] font-mono text-[#7C8CFF] uppercase tracking-wider block font-semibold">
              ENTRY POINTS / ROUTES
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(categorized.routes.length > 0 ? categorized.routes : files.slice(0, 2)).map((f, i) => {
                const nodeFindings = getFindingsForFile(f.path || f.filename);
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
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 truncate">
                        <FileCode className="w-4 h-4 text-[#7C8CFF]" />
                        <span className="text-xs font-mono font-semibold text-[#F4F7FB] truncate">
                          {f.path || f.filename || `route_${i}.py`}
                        </span>
                      </div>
                      {nodeFindings.length > 0 && (
                        <span className="cm-badge cm-badge-critical">
                          {nodeFindings.length} issue
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex justify-center text-[#687386]">
            <ArrowDown className="w-5 h-5" />
          </div>

          {/* Layer 2: Services / Business Logic */}
          <div className="space-y-2">
            <span className="text-[11px] font-mono text-[#F4C95D] uppercase tracking-wider block font-semibold">
              SERVICES / BUSINESS LOGIC
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(categorized.services.length > 0 ? categorized.services : files.slice(2, 4)).map((f, i) => {
                const nodeFindings = getFindingsForFile(f.path || f.filename);
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
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 truncate">
                        <FileCode className="w-4 h-4 text-[#F4C95D]" />
                        <span className="text-xs font-mono font-semibold text-[#F4F7FB] truncate">
                          {f.path || f.filename || `service_${i}.py`}
                        </span>
                      </div>
                      {nodeFindings.length > 0 && (
                        <span className="cm-badge cm-badge-high">
                          {nodeFindings.length} issue
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex justify-center text-[#687386]">
            <ArrowDown className="w-5 h-5" />
          </div>

          {/* Layer 3: Database & Sinks */}
          <div className="space-y-2">
            <span className="text-[11px] font-mono text-[#36D399] uppercase tracking-wider block font-semibold">
              DATABASE / EXECUTION SINKS
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(categorized.database.length > 0 ? categorized.database : files.slice(4, 6)).map((f, i) => {
                const nodeFindings = getFindingsForFile(f.path || f.filename);
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
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 truncate">
                        <FileCode className="w-4 h-4 text-[#36D399]" />
                        <span className="text-xs font-mono font-semibold text-[#F4F7FB] truncate">
                          {f.path || f.filename || `database_${i}.py`}
                        </span>
                      </div>
                      {nodeFindings.length > 0 && (
                        <span className="cm-badge cm-badge-critical">
                          {nodeFindings.length} issue
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right 4 Cols: Selected Node Details */}
        <div className="lg:col-span-4 cm-card p-5 border-[#232936] bg-[#10131A] space-y-4">
          <div className="border-b border-[#232936] pb-3">
            <span className="text-xs font-mono text-[#687386] uppercase tracking-wider block">
              COMPONENT DETAILS
            </span>
            <h3 className="text-sm font-bold font-mono text-[#F4F7FB] mt-1 truncate">
              {selectedNode?.path || selectedNode?.filename || "Select a Node"}
            </h3>
          </div>

          {selectedNode ? (
            <div className="space-y-4 text-xs font-mono">
              <div className="space-y-1">
                <span className="text-[#687386] block text-[10px]">ASSOCIATED FINDINGS</span>
                {getFindingsForFile(selectedNode.path || selectedNode.filename).length === 0 ? (
                  <p className="text-[#36D399] text-[11px]">✓ No vulnerabilities detected in component.</p>
                ) : (
                  getFindingsForFile(selectedNode.path || selectedNode.filename).map((f, i) => (
                    <div key={i} className="p-2 rounded bg-[#090B10] border border-[#232936] text-[#FF5D73]">
                      Line {f.line || 1}: {f.title || f.type}
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs text-[#687386]">Click any architectural node to inspect parameters.</p>
          )}
        </div>
      </div>
    </div>
  );
}
