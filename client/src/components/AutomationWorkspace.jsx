import React from "react";
import {
  AlertTriangle,
  Bomb,
  CheckCircle2,
  Download,
  Flame,
  Loader2,
  Minus,
  RotateCcw,
  ShieldCheck,
  Skull,
  Square,
  XCircle,
} from "lucide-react";
import { fixedProjectZipUrl } from "../api/client";

const STAGES = [
  {
    id: "defender",
    label: "Defender",
    icon: ShieldCheck,
    lines: ["Analyzing confirmed findings", "Running bounded fix cycles", "Verifying source revision"],
  },
  {
    id: "hacker",
    label: "Hacker Mode",
    icon: Skull,
    lines: ["Mapping attack surfaces", "Analyzing trust boundaries", "Ranking high-interest areas"],
  },
  {
    id: "brutal",
    label: "Deep Audit",
    icon: Flame,
    lines: ["Reviewing architecture", "Evaluating reliability", "Checking production readiness"],
  },
  {
    id: "blast_radius",
    label: "Blast Radius",
    icon: Bomb,
    lines: ["Building dependency graph", "Calculating downstream impact", "Ranking critical components"],
  },
];

const TERMINAL = new Set(["complete", "paused", "failed", "stopped"]);

function stageTone(stage) {
  const status = stage?.status || "pending";
  if (status === "complete") return "text-[#36D399] border-[#36D399]/35 bg-[#36D399]/10";
  if (status === "running") return "text-[#7C8CFF] border-[#7C8CFF]/40 bg-[#7C8CFF]/10";
  if (["paused", "skipped"].includes(status)) return "text-[#F4C95D] border-[#F4C95D]/35 bg-[#F4C95D]/10";
  if (status === "failed") return "text-[#FF5D73] border-[#FF5D73]/35 bg-[#FF5D73]/10";
  return "text-[#687386] border-[#232936] bg-[#10131A]";
}

function statusIcon(stage) {
  const status = stage?.status || "pending";
  if (status === "complete") return <CheckCircle2 className="w-4 h-4" />;
  if (status === "running") return <Loader2 className="w-4 h-4 animate-spin" />;
  if (["paused", "skipped"].includes(status)) return <AlertTriangle className="w-4 h-4" />;
  if (status === "failed") return <XCircle className="w-4 h-4" />;
  return <span className="w-2 h-2 rounded-full bg-current opacity-70" />;
}

function StageRow({ config, stage, active }) {
  const Icon = config.icon;
  return (
    <div className={`rounded-lg border p-4 transition-all ${stageTone(stage)} ${active ? "shadow-[0_0_30px_rgba(124,140,255,0.12)]" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg border border-current/30 bg-[#090B10]/60 flex items-center justify-center">
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-bold text-[#F4F7FB]">{config.label}</div>
            <div className="text-[10px] font-mono uppercase tracking-wider">{stage?.status || "pending"}</div>
          </div>
        </div>
        <div className="shrink-0">{statusIcon(stage)}</div>
      </div>
      {active && (
        <div className="mt-3 space-y-1 text-xs text-[#9AA4B2]">
          {config.lines.map((line) => (
            <div key={line} className="flex items-center gap-2">
              <span className="w-1 h-1 rounded-full bg-current" />
              <span>{line}</span>
            </div>
          ))}
        </div>
      )}
      {stage?.manual_review_required && <p className="mt-3 text-xs text-[#F4D98A]">Manual review required for remaining Defender findings.</p>}
      {stage?.error && <p className="mt-3 text-xs text-[#FFB4C0]">{stage.error}</p>}
    </div>
  );
}

function FinalReport({ status, projectId, onOpenReport }) {
  const report = status?.final_report;
  if (!report) return null;
  const defender = report.defender || {};
  const hacker = report.hacker || {};
  const brutal = report.brutal || {};
  const blast = report.blast_radius || {};

  return (
    <div className="rounded-lg border border-[#232936] bg-[#090B10] p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-bold text-[#36D399]">AUTOMATION COMPLETE</div>
          <p className="text-xs text-[#9AA4B2]">Repository hardened and analyzed.</p>
        </div>
        {projectId && (
          <a href={fixedProjectZipUrl(projectId)} download className="cm-btn-primary text-xs py-2">
            <Download className="w-4 h-4" />
            <span>Download Hardened ZIP</span>
          </a>
        )}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
        <div className="rounded-lg bg-[#10131A] border border-[#232936] p-3">
          <div className="font-mono text-[#7C8CFF] mb-1">DEFENDER</div>
          <div>{defender.confirmed_findings || 0} confirmed findings</div>
          <div>{defender.automatically_fixed || 0} automatically fixed</div>
          <div>{defender.requires_manual_review || 0} requires manual review</div>
          <div>{defender.fix_cycles || 0} fix cycles</div>
        </div>
        <div className="rounded-lg bg-[#10131A] border border-[#232936] p-3">
          <div className="font-mono text-[#7C8CFF] mb-1">HACKER MODE</div>
          <div>{hacker.attack_surfaces || 0} attack surfaces</div>
          <div>{hacker.risk_paths || 0} potential risk paths</div>
        </div>
        <div className="rounded-lg bg-[#10131A] border border-[#232936] p-3">
          <div className="font-mono text-[#7C8CFF] mb-1">BRUTAL AUDIT</div>
          <div>{brutal.overall_score ?? "N/A"} / 10</div>
          <div>{brutal.verdict || brutal.status || "complete"}</div>
        </div>
        <div className="rounded-lg bg-[#10131A] border border-[#232936] p-3">
          <div className="font-mono text-[#7C8CFF] mb-1">BLAST RADIUS</div>
          <div>{blast.high_impact_components || 0} high-impact components</div>
          <div>Highest: {blast.highest?.id || "N/A"} {blast.highest?.score ? `- ${blast.highest.score}/10` : ""}</div>
        </div>
      </div>
      <button type="button" onClick={onOpenReport} className="cm-btn-secondary text-xs">
        View Complete Report
      </button>
    </div>
  );
}

export default function AutomationWorkspace({
  status,
  projectId,
  minimized,
  onMinimize,
  onRestore,
  onStop,
  stopping,
  onOpenReport,
}) {
  if (!status) return null;
  const activeIndex = Math.max(0, STAGES.findIndex((stage) => stage.id === status.current_stage));
  const isTerminal = TERMINAL.has(status.status);

  if (minimized) {
    const active = STAGES[activeIndex] || STAGES[0];
    return (
      <button
        type="button"
        onClick={onRestore}
        className="fixed bottom-5 right-5 z-40 rounded-lg border border-[#7C8CFF]/40 bg-[#10131A] px-4 py-3 text-left shadow-2xl shadow-[#000]/40 hover:border-[#7C8CFF]"
      >
        <div className="text-[10px] font-mono uppercase tracking-wider text-[#7C8CFF]">CODE MASTER AUTOMATION</div>
        <div className="text-sm font-semibold text-[#F4F7FB]">Step {activeIndex + 1}/4 - {active.label}</div>
        <div className="text-xs text-[#9AA4B2]">{status.message}</div>
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-[#090B10]/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-5xl max-h-[92vh] overflow-y-auto rounded-xl border border-[#232936] bg-[#10131A] shadow-2xl">
        <div className="sticky top-0 z-10 bg-[#10131A]/95 border-b border-[#232936] p-5 flex items-start justify-between gap-4">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[#7C8CFF]">CODE MASTER AI</div>
            <h2 className="text-xl font-extrabold text-[#F4F7FB]">Automated Hardening Mission</h2>
            <p className="text-xs text-[#9AA4B2] mt-1">ONE REPOSITORY IN. HARDENED, VERIFIED AND DEEPLY ANALYZED CODE OUT.</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onMinimize} className="cm-btn-secondary text-xs" title="Minimize automation">
              <Minus className="w-4 h-4" />
              <span>Minimize</span>
            </button>
            {!isTerminal && (
              <button type="button" onClick={onStop} disabled={stopping} className="cm-btn-secondary text-xs" title="Stop at safe boundary">
                {stopping ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
                <span>{stopping ? "Stopping..." : "Stop"}</span>
              </button>
            )}
          </div>
        </div>

        <div className="p-5 space-y-5">
          <div className="rounded-lg border border-[#232936] bg-[#090B10] p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-[#F4F7FB]">Repository Loaded</div>
              <div className="text-xs text-[#9AA4B2]">{status.message || "Automation is running."}</div>
            </div>
            <div className="text-xs font-mono text-[#7C8CFF] uppercase">{status.status}</div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {STAGES.map((stage, index) => (
              <StageRow
                key={stage.id}
                config={stage}
                stage={status[stage.id]}
                active={!isTerminal && index === activeIndex}
              />
            ))}
          </div>

          {status.status === "paused" && (
            <div className="rounded-lg border border-[#F4C95D]/35 bg-[#F4C95D]/10 p-4 text-sm text-[#F4F7FB]">
              <div className="font-bold">AUTOMATION PAUSED</div>
              <p className="text-xs text-[#F4D98A] mt-1">{status.error || status.message}</p>
            </div>
          )}

          <FinalReport status={status} projectId={projectId} onOpenReport={onOpenReport} />

          {isTerminal && !status.final_report && (
            <button type="button" onClick={onOpenReport} className="cm-btn-secondary text-xs">
              <RotateCcw className="w-4 h-4" />
              <span>Return To Workspace</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
