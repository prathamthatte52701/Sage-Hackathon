import React, { useState, useEffect } from "react";
import {
  ShieldAlert,
  Search,
  CheckCircle2,
  ChevronRight,
} from "lucide-react";
import CodeViewer from "./CodeViewer";
import EvidencePanel from "./EvidencePanel";
import { getProjectFile } from "../api/client";

export default function FindingExplorer({
  project,
  selectedFinding,
  onSelectFinding,
  onGenerateFix,
  generatingFix,
  onReasonFinding,
  reasoning,
}) {
  const findings = project?.findings ?? [];
  const files = project?.files ?? [];

  const [severityFilter, setSeverityFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [loadedSource, setLoadedSource] = useState("");
  const [sourceStatus, setSourceStatus] = useState("idle");

  // Select first finding by default if none selected
  const activeFinding = selectedFinding || (findings.length > 0 ? findings[0] : null);

  const activeFileContent = (() => {
    if (!activeFinding) return "";

    const filePath = activeFinding.file || activeFinding.path;
    const matchingFile = files.find(
      (f) => f.path === filePath || f.filename === filePath || f.name === filePath
    );

    return matchingFile?.content || loadedSource;
  })();

  useEffect(() => {
    const filePath = activeFinding?.file || activeFinding?.path;
    const embedded = files.find((file) => file.path === filePath)?.content;
    if (!filePath || embedded) {
      setLoadedSource(embedded || "");
      setSourceStatus(filePath ? "ready" : "idle");
      return undefined;
    }

    let cancelled = false;
    setLoadedSource("");
    setSourceStatus("loading");
    getProjectFile(project?.project_id || project?._id, filePath)
      .then((file) => {
        if (!cancelled) {
          setLoadedSource(file.content || "");
          setSourceStatus(file.content ? "ready" : "unavailable");
        }
      })
      .catch(() => {
        if (!cancelled) setSourceStatus("unavailable");
      });
    return () => { cancelled = true; };
  }, [activeFinding, files, project?.project_id, project?._id]);

  // Filter findings dynamically
  const filteredFindings = findings.filter((f) => {
    const matchesSev = severityFilter === "all" || f.severity === severityFilter;
    const matchesSearch =
      !searchQuery.trim() ||
      (f.title || f.type || f.message || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (f.file || "").toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSev && matchesSearch;
  });

  const severityCounts = {
    all: findings.length,
    critical: findings.filter((f) => f.severity === "critical").length,
    high: findings.filter((f) => f.severity === "high").length,
    medium: findings.filter((f) => f.severity === "medium").length,
    low: findings.filter((f) => f.severity === "low").length,
  };

  // Keyboard navigation (Up/Down arrow keys to switch findings)
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (filteredFindings.length === 0) return;

      const currentIndex = filteredFindings.indexOf(activeFinding);

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const nextIndex = (currentIndex + 1) % filteredFindings.length;
        onSelectFinding?.(filteredFindings[nextIndex]);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prevIndex = (currentIndex - 1 + filteredFindings.length) % filteredFindings.length;
        onSelectFinding?.(filteredFindings[prevIndex]);
      } else if (e.key === "Enter" && activeFinding) {
        e.preventDefault();
        onGenerateFix?.(activeFinding);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [filteredFindings, activeFinding, onSelectFinding, onGenerateFix]);

  return (
    <div className="min-h-[calc(100vh-5rem)] lg:h-[calc(100vh-5rem)] grid grid-cols-1 lg:grid-cols-12 gap-4 p-0 sm:p-2 lg:p-4 overflow-visible lg:overflow-hidden select-none">
      {/* COLUMN 1: Findings Navigation Sidebar (3 cols) */}
      <div className="lg:col-span-3 cm-card border-[#232936] bg-[#10131A] flex flex-col h-[360px] lg:h-full overflow-hidden">
        {/* Header & Filter Controls */}
        <div className="p-3 border-b border-[#232936] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-semibold text-[#F4F7FB] flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5 text-[#7C8CFF]" />
              FINDINGS ({filteredFindings.length})
            </span>
          </div>

          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[#687386] absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search findings or files..."
              className="w-full pl-8 pr-3 py-1.5 rounded-md border border-[#232936] bg-[#090B10] text-xs text-[#F4F7FB] font-mono placeholder:text-[#687386] focus:border-[#7C8CFF] focus:outline-none"
            />
          </div>

          {/* Severity Pills */}
          <div className="flex gap-1 overflow-x-auto pb-1">
            {["all", "critical", "high", "medium", "low"].map((sev) => (
              <button
                key={sev}
                onClick={() => setSeverityFilter(sev)}
                className={`px-2 py-1 rounded text-[10px] font-mono font-semibold capitalize transition-all ${
                  severityFilter === sev
                    ? "bg-[#7C8CFF] text-[#090B10]"
                    : "bg-[#090B10] text-[#9AA4B2] border border-[#232936] hover:text-[#F4F7FB]"
                }`}
              >
                {sev} ({severityCounts[sev]})
              </button>
            ))}
          </div>
        </div>

        {/* Findings List Scrollable */}
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {filteredFindings.length === 0 ? (
            <div className="p-6 text-center text-xs text-[#687386]">
              No findings matching filter criteria.
            </div>
          ) : (
            filteredFindings.map((finding, idx) => {
              const isSelected = activeFinding === finding;
              const isDeterministic =
                finding.deterministic_evidence === true ||
                finding.source === "deterministic" ||
                finding.source === "AST" ||
                String(finding.evidence_type || "").startsWith("deterministic") ||
                String(finding.evidence_type || "").startsWith("ast_") ||
                String(finding.evidence_type || "").startsWith("literal_");
              const isGrounded = finding.grounded !== false;

              return (
                <div
                  key={idx}
                  onClick={() => onSelectFinding?.(finding)}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    isSelected
                      ? "bg-[#151922] border-[#7C8CFF] shadow-md shadow-[#7C8CFF]/10"
                      : "bg-[#090B10] border-[#232936] hover:border-[#7C8CFF]/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <span
                      className={`cm-badge ${
                        finding.severity === "critical"
                          ? "cm-badge-critical"
                          : finding.severity === "high"
                          ? "cm-badge-high"
                          : finding.severity === "medium"
                          ? "cm-badge-medium"
                          : "cm-badge-low"
                      }`}
                    >
                      {finding.severity || "HIGH"}
                    </span>
                    
                    {isGrounded && (
                      <span className="text-[10px] font-mono text-[#7C8CFF] flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-[#36D399]" />
                        {isDeterministic ? "Deterministic" : "Grounded"}
                      </span>
                    )}
                  </div>

                  <h4 className="text-xs font-semibold text-[#F4F7FB] truncate">
                    {finding.title || finding.message || finding.type || "Finding"}
                  </h4>

                  <div className="text-[11px] font-mono text-[#687386] truncate mt-1 flex items-center justify-between">
                    <span>
                      {finding.file}:{finding.line || 1}
                    </span>
                    <ChevronRight className="w-3 h-3 text-[#687386]" />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* COLUMN 2: Code Viewer / Editor Workspace (5 cols) */}
      <div className="lg:col-span-5 h-[520px] lg:h-full overflow-hidden">
        {sourceStatus === "unavailable" ? (
          <div className="cm-card border-[#232936] bg-[#10131A] h-full flex items-center justify-center p-6 text-center text-xs text-[#687386]">
            Source is unavailable for this finding.
          </div>
        ) : (
          <CodeViewer
            fileContent={activeFileContent}
            filePath={activeFinding?.file}
            highlightLine={activeFinding?.line}
            height="100%"
          />
        )}
      </div>

      {/* COLUMN 3: Evidence & Explanation Panel (4 cols) */}
      <div className="lg:col-span-4 h-auto lg:h-full overflow-hidden">
        <EvidencePanel
          finding={activeFinding}
          onGenerateFix={() => onGenerateFix?.(activeFinding)}
          generatingFix={generatingFix}
          onReasonFinding={() => onReasonFinding?.(activeFinding)}
          reasoning={reasoning}
        />
      </div>
    </div>
  );
}
