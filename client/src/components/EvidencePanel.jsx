import React, { useState } from "react";
import {
  ShieldAlert,
  ArrowDown,
  Sparkles,
  BookOpen,
  CheckCircle2,
  Cpu,
  Layers,
  Wrench,
  HelpCircle,
  ExternalLink,
} from "lucide-react";

export default function EvidencePanel({
  finding,
  onGenerateFix,
  onReasonFinding,
  generatingFix,
  reasoning,
}) {
  const [showStandardDetails, setShowStandardDetails] = useState(false);

  if (!finding) {
    return (
      <div className="cm-card p-6 border-[#232936] bg-[#10131A] text-center text-xs text-[#687386] h-full flex flex-col items-center justify-center space-y-3">
        <ShieldAlert className="w-8 h-8 text-[#232936]" />
        <div>
          <p className="font-semibold text-[#9AA4B2]">No Finding Selected</p>
          <p className="text-[11px] text-[#687386] mt-1">
            Click any finding in the explorer list to inspect evidence, standards, and fixes.
          </p>
        </div>
      </div>
    );
  }

  // Parse or extract evidence details if available
  const isDeterministic = finding.source === "AST" || finding.type?.toLowerCase().includes("sql") || Boolean(finding.line);
  const isGrounded = finding.grounded !== false;
  const cweCode = finding.cwe || finding.standard || (finding.title?.toLowerCase().includes("sql") ? "CWE-89" : "CWE-79");

  // Sample data-flow chain representation (Specification §14)
  const evidenceChain = [
    { label: "SOURCE", detail: finding.source_variable || "request.query.id / user input" },
    { label: "VARIABLE", detail: finding.variable || "userId" },
    { label: "EXPRESSION", detail: finding.query_snippet || finding.evidence_snippet || `Line ${finding.line || 42}: ${finding.code_context || "user payload execution"}` },
    { label: "SINK", detail: finding.sink || "database.execute(query)" },
  ];

  return (
    <div className="cm-card border-[#232936] bg-[#10131A] overflow-y-auto h-full p-5 space-y-6">
      {/* Header Title & Badges */}
      <div className="space-y-3 border-b border-[#232936] pb-4">
        <div className="flex items-center justify-between">
          <span
            className={`cm-badge ${
              finding.severity === "critical"
                ? "cm-badge-critical"
                : finding.severity === "high"
                ? "cm-badge-high"
                : "cm-badge-medium"
            }`}
          >
            {finding.severity || "HIGH"}
          </span>

          <div className="flex items-center gap-1.5 text-[10px] font-mono text-[#7C8CFF] bg-[#7C8CFF]/10 px-2 py-0.5 rounded border border-[#7C8CFF]/20">
            <CheckCircle2 className="w-3 h-3 text-[#36D399]" />
            <span>{isDeterministic ? "Deterministic AST" : "AI Grounded"}</span>
          </div>
        </div>

        <div>
          <h3 className="text-base font-bold text-[#F4F7FB] tracking-tight">
            {finding.title || finding.type || "Security Finding"}
          </h3>
          <p className="text-xs font-mono text-[#687386] mt-1 truncate">
            {finding.file}:{finding.line || 1}
          </p>
        </div>
      </div>

      {/* Signature UX: Evidence Panel Data-Flow Chain (Specification §14) */}
      <div className="space-y-3">
        <h4 className="text-xs font-mono font-semibold text-[#7C8CFF] uppercase tracking-wider flex items-center gap-1.5">
          <Layers className="w-3.5 h-3.5" />
          <span>EVIDENCE CHAIN</span>
        </h4>

        <div className="p-3.5 rounded-lg bg-[#090B10] border border-[#232936] space-y-2">
          {evidenceChain.map((step, idx) => (
            <React.Fragment key={idx}>
              <div className="flex items-start gap-2 text-xs">
                <span className="font-mono text-[10px] font-bold text-[#7C8CFF] bg-[#7C8CFF]/10 px-1.5 py-0.5 rounded shrink-0">
                  {step.label}
                </span>
                <span className="font-mono text-[11px] text-[#F4F7FB] break-all">
                  {step.detail}
                </span>
              </div>
              {idx < evidenceChain.length - 1 && (
                <div className="flex justify-center py-0.5 text-[#687386]">
                  <ArrowDown className="w-3 h-3" />
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* "Why This Matters" Section (Specification §15) */}
      <div className="space-y-3">
        <h4 className="text-xs font-mono font-semibold text-[#F4C95D] uppercase tracking-wider flex items-center gap-1.5">
          <BookOpen className="w-3.5 h-3.5" />
          <span>WHY THIS MATTERS</span>
        </h4>

        <div className="p-3.5 rounded-lg bg-[#090B10] border border-[#232936] space-y-3 text-xs">
          <div>
            <span className="text-[#687386] font-medium block text-[11px] uppercase tracking-wide">
              IMPACT
            </span>
            <p className="text-[#F4F7FB] mt-0.5 leading-relaxed">
              {finding.description || finding.impact || "Unsanitized user-controlled payload reaches sensitive query execution."}
            </p>
          </div>

          <div>
            <span className="text-[#687386] font-medium block text-[11px] uppercase tracking-wide">
              ENGINEERING STANDARD
            </span>
            <div className="flex items-center justify-between mt-1">
              <span className="font-mono font-semibold text-[#7C8CFF] bg-[#7C8CFF]/10 px-2 py-0.5 rounded border border-[#7C8CFF]/20">
                {cweCode}
              </span>
              <button
                onClick={() => setShowStandardDetails(!showStandardDetails)}
                className="text-[11px] text-[#9AA4B2] hover:text-[#F4F7FB] flex items-center gap-1"
              >
                <span>Details</span>
                <ExternalLink className="w-3 h-3" />
              </button>
            </div>
            {showStandardDetails && (
              <p className="text-[11px] text-[#9AA4B2] mt-2 p-2 rounded bg-[#151922] border border-[#232936]">
                CWE-89: Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection'). Always use parameterized queries.
              </p>
            )}
          </div>

          <div>
            <span className="text-[#687386] font-medium block text-[11px] uppercase tracking-wide">
              RECOMMENDED REMEDIATION
            </span>
            <p className="text-[#36D399] mt-0.5 font-mono text-[11px]">
              {finding.recommendation || "Replace string concatenation with parameterized placeholder query arguments."}
            </p>
          </div>
        </div>
      </div>

      {/* Action Buttons: Generate Fix / Reason Finding (Specification §16) */}
      <div className="pt-2 space-y-2">
        <button
          onClick={onGenerateFix}
          disabled={generatingFix}
          className="w-full cm-btn-primary justify-center py-2.5 shadow-lg shadow-[#7C8CFF]/15"
        >
          <Wrench className={`w-4 h-4 ${generatingFix ? "animate-spin" : ""}`} />
          <span>{generatingFix ? "Generating Validated Fix..." : "Generate Fix"}</span>
        </button>

        {onReasonFinding && (
          <button
            onClick={onReasonFinding}
            disabled={reasoning}
            className="w-full cm-btn-secondary justify-center py-2 text-xs"
          >
            <HelpCircle className="w-3.5 h-3.5 text-[#7C8CFF]" />
            <span>{reasoning ? "Analyzing Deep Reason..." : "Deep Reason Analysis"}</span>
          </button>
        )}
      </div>
    </div>
  );
}
