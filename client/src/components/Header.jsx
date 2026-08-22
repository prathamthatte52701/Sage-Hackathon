import React from "react";
import { RefreshCw, Download, ShieldCheck, Zap } from "lucide-react";
import { fixedProjectZipUrl } from "../api/client";

export default function Header({
  activeTab,
  project,
  onReanalyze,
  reanalyzing,
}) {
  const getTabTitle = () => {
    switch (activeTab) {
      case "overview":
        return "Project Overview & Health";
      case "findings":
        return "Finding Explorer (IDE Workspace)";
      case "paste_review":
        return "Single File Snippet Review";
      case "projects":
        return "Import & Manage Codebase";
      case "chat":
        return "Codebase Intelligence Chat";
      case "architecture":
        return "System Dependency Graph";
      case "history":
        return "Review History & Logs";
      default:
        return "Code Master AI Workspace";
    }
  };

  return (
    <header className="h-16 border-b border-[#232936] bg-[#090B10]/80 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-20">
      {/* Title */}
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold text-[#F4F7FB] tracking-tight">
          {getTabTitle()}
        </h1>
        {project && (
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-[#151922] border border-[#232936] text-[#9AA4B2] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#36D399]" />
            {project.name || project.project_id || "Active Project"}
          </span>
        )}
      </div>

      {/* Action Controls */}
      <div className="flex items-center gap-3">
        {project && (
          <>
            {/* Quick Score Pill */}
            {project.score && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#10131A] border border-[#232936]">
                <ShieldCheck className="w-4 h-4 text-[#7C8CFF]" />
                <div className="flex items-baseline gap-1 text-xs">
                  <span className="text-[#687386] font-medium">Health:</span>
                  <span className="font-mono font-bold text-[#F4F7FB]">
                    {(project.score.overall_score || project.score.health_score || 0).toFixed(1)}
                  </span>
                  <span className="text-[#687386]">/100</span>
                </div>
              </div>
            )}

            {/* Reanalyze Button */}
            {onReanalyze && (
              <button
                onClick={onReanalyze}
                disabled={reanalyzing}
                className="cm-btn-secondary text-xs py-1.5"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${reanalyzing ? "animate-spin text-[#7C8CFF]" : ""}`}
                />
                <span>{reanalyzing ? "Reanalyzing..." : "Reanalyze"}</span>
              </button>
            )}

            {/* Download Fixed ZIP */}
            {project.project_id && (
              <a
                href={fixedProjectZipUrl(project.project_id)}
                download
                className="cm-btn-primary text-xs py-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download Fixed Code</span>
              </a>
            )}
          </>
        )}
      </div>
    </header>
  );
}
