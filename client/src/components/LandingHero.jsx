import React, { useState } from "react";
import {
  ArrowRight,
  Code2,
  FolderGit2,
  Zap,
  Lock,
  Layers,
  Sparkles,
  Terminal,
} from "lucide-react";

export default function LandingHero({ onSelectAction }) {
  const [activeCodeTab, setActiveCodeTab] = useState("vulnerable");

  return (
    <div className="max-w-5xl mx-auto py-8 px-6 space-y-12 text-center select-none relative z-10">
      {/* 1. Header & Hero Badge */}
      <div className="space-y-5 max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#7C8CFF]/10 border border-[#7C8CFF]/30 text-[#7C8CFF] text-xs font-mono font-semibold">
          <Sparkles className="w-4 h-4 text-[#7C8CFF]" />
          <span>EVIDENCE-FIRST CODE INTELLIGENCE ENGINE</span>
        </div>

        <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-[#F4F7FB] leading-none">
          CODE MASTER <span className="text-[#7C8CFF]">AI</span>
        </h1>

        <p className="text-base sm:text-lg text-[#9AA4B2] font-normal leading-relaxed">
          Understand your codebase. Find what matters. Fix it safely.
        </p>

        <p className="text-xs text-[#687386] font-mono tracking-wide">
          Deterministic AST analysis + AI reasoning grounded in real repository evidence.
        </p>

        {/* Action Buttons */}
        <div className="flex flex-wrap justify-center gap-3 pt-2">
          <button
            onClick={() => onSelectAction("projects")}
            className="cm-btn-primary px-7 py-3 text-xs font-semibold shadow-lg shadow-[#7C8CFF]/20 group"
          >
            <FolderGit2 className="w-4 h-4 text-[#090B10]" />
            <span>Import Project (ZIP / GitHub)</span>
            <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-0.5 transition-transform" />
          </button>

          <button
            onClick={() => onSelectAction("paste_review")}
            className="cm-btn-secondary px-6 py-3 text-xs font-medium"
          >
            <Code2 className="w-4 h-4 text-[#7C8CFF]" />
            <span>Paste Code Snippet</span>
          </button>
        </div>
      </div>

      {/* 2. Interactive Code Scanner Demo Container */}
      <div className="max-w-4xl mx-auto space-y-3">
        <div className="flex items-center justify-between text-xs font-mono text-[#9AA4B2] px-1">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-[#7C8CFF]" />
            <span className="font-semibold text-[#F4F7FB]">CODE INTELLIGENCE DEMO</span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setActiveCodeTab("vulnerable")}
              className={`px-3 py-1 rounded text-[11px] font-semibold transition-all ${
                activeCodeTab === "vulnerable"
                  ? "bg-[#FF5D73]/15 text-[#FF5D73] border border-[#FF5D73]/30"
                  : "bg-[#10131A] text-[#687386] border border-[#232936]"
              }`}
            >
              Vulnerabilities Detected
            </button>
            <button
              onClick={() => setActiveCodeTab("fixed")}
              className={`px-3 py-1 rounded text-[11px] font-semibold transition-all ${
                activeCodeTab === "fixed"
                  ? "bg-[#36D399]/15 text-[#36D399] border border-[#36D399]/30"
                  : "bg-[#10131A] text-[#687386] border border-[#232936]"
              }`}
            >
              Validated Patch Applied
            </button>
          </div>
        </div>

        <div className="cm-card border-[#232936] bg-[#090B10] overflow-hidden text-left shadow-xl">
          {/* Header Bar */}
          <div className="h-9 px-4 bg-[#10131A] border-b border-[#232936] flex items-center justify-between font-mono text-xs text-[#687386]">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#FF5D73]" />
              <span className="w-2.5 h-2.5 rounded-full bg-[#F4C95D]" />
              <span className="w-2.5 h-2.5 rounded-full bg-[#36D399]" />
              <span className="ml-2 text-[#9AA4B2] font-semibold">server/routes/users.py</span>
            </div>
            <span className="text-[11px] text-[#7C8CFF] font-semibold">
              {activeCodeTab === "vulnerable" ? "AST FINDING (CWE-89)" : "PATCH VALIDATED"}
            </span>
          </div>

          {/* Code Window */}
          <div className="p-5 font-mono text-xs leading-relaxed space-y-2 bg-[#090B10]">
            {activeCodeTab === "vulnerable" ? (
              <>
                <div className="text-[#687386]"># Line 40: User query handler</div>
                <div className="text-[#F4F7FB]">@app.get("/users/search")</div>
                <div className="text-[#F4F7FB]">def search_users(user_id: str):</div>
                <div className="p-2.5 rounded bg-[#FF5D73]/15 border-l-4 border-[#FF5D73] text-[#FF5D73] flex items-center justify-between">
                  <span>query = "SELECT * FROM users WHERE id = " + user_id</span>
                  <span className="text-[10px] font-bold bg-[#FF5D73] text-[#090B10] px-1.5 py-0.5 rounded">
                    RAW SINK
                  </span>
                </div>
                <div className="text-[#F4F7FB]">    return db.execute(query)</div>
              </>
            ) : (
              <>
                <div className="text-[#687386]"># Line 40: Parameterized Query Execution</div>
                <div className="text-[#F4F7FB]">@app.get("/users/search")</div>
                <div className="text-[#F4F7FB]">def search_users(user_id: str):</div>
                <div className="p-2.5 rounded bg-[#36D399]/15 border-l-4 border-[#36D399] text-[#36D399] flex items-center justify-between">
                  <span>query = "SELECT * FROM users WHERE id = %s"</span>
                  <span className="text-[10px] font-bold bg-[#36D399] text-[#090B10] px-1.5 py-0.5 rounded">
                    SAFE ARGUMENT
                  </span>
                </div>
                <div className="text-[#36D399]">    return db.execute(query, (user_id,))</div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* 3. Capability Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left max-w-4xl mx-auto">
        <div className="cm-card p-5 border-[#232936] bg-[#10131A] space-y-2">
          <div className="w-8 h-8 rounded-lg bg-[#FF5D73]/15 border border-[#FF5D73]/30 flex items-center justify-center text-[#FF5D73]">
            <Zap className="w-4 h-4" />
          </div>
          <h3 className="text-xs font-bold text-[#F4F7FB]">Deterministic AST Scans</h3>
          <p className="text-[11px] text-[#9AA4B2] leading-relaxed">
            Static analysis rules scan python and javascript AST trees to catch vulnerabilities with 0 hallucinations.
          </p>
        </div>

        <div className="cm-card p-5 border-[#232936] bg-[#10131A] space-y-2">
          <div className="w-8 h-8 rounded-lg bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
            <Layers className="w-4 h-4" />
          </div>
          <h3 className="text-xs font-bold text-[#F4F7FB]">Grounded Evidence Chain</h3>
          <p className="text-[11px] text-[#9AA4B2] leading-relaxed">
            Every finding traces exact data flows: Source → Variable → Expression → Execution Sink.
          </p>
        </div>

        <div className="cm-card p-5 border-[#232936] bg-[#10131A] space-y-2">
          <div className="w-8 h-8 rounded-lg bg-[#36D399]/15 border border-[#36D399]/30 flex items-center justify-center text-[#36D399]">
            <Lock className="w-4 h-4" />
          </div>
          <h3 className="text-xs font-bold text-[#F4F7FB]">Safe 5-Point Patch Verification</h3>
          <p className="text-[11px] text-[#9AA4B2] leading-relaxed">
            Fixes pass string hash uniqueness, target line matching, and overlap checks before mutation.
          </p>
        </div>
      </div>
    </div>
  );
}
