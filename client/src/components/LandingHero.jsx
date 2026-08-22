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
import Card3DTilt from "./Card3DTilt";

export default function LandingHero({ onSelectAction }) {
  const [activeCodeTab, setActiveCodeTab] = useState("vulnerable"); // "vulnerable" | "fixed"

  return (
    <div className="max-w-6xl mx-auto py-6 sm:py-10 px-2 sm:px-6 space-y-10 sm:space-y-14 text-center select-none relative z-10">
      {/* 1. Futuristic Hero Header & Badge */}
      <div className="space-y-6 max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-2.5 px-4 py-1.5 rounded-full bg-[#7C8CFF]/10 border border-[#7C8CFF]/30 text-[#7C8CFF] text-xs font-mono font-semibold shadow-lg shadow-[#7C8CFF]/10">
          <Sparkles className="w-4 h-4 text-[#7C8CFF]" />
          <span>EVIDENCE-FIRST CODE INTELLIGENCE ENGINE</span>
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-[#F4F7FB] leading-none">
          CODE MASTER <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#7C8CFF] via-[#57B8FF] to-[#36D399]">AI</span>
        </h1>

        <p className="text-lg sm:text-xl text-[#9AA4B2] font-normal leading-relaxed">
          Understand your codebase. Find what matters. Fix it safely.
        </p>

        <p className="text-xs text-[#687386] font-mono tracking-wide">
          Deterministic AST scanners plus AI review grounded in source code evidence.
        </p>

        {/* Action CTA Buttons */}
        <div className="flex flex-wrap justify-center gap-4 pt-4">
          <button
            onClick={() => onSelectAction("projects")}
            className="cm-btn-primary px-8 py-3.5 text-sm font-semibold shadow-xl shadow-[#7C8CFF]/25 hover:shadow-[#7C8CFF]/40 transform hover:-translate-y-0.5 transition-all group"
          >
            <FolderGit2 className="w-5 h-5 text-[#090B10]" />
            <span>Import Project (ZIP / GitHub)</span>
            <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
          </button>

          <button
            onClick={() => onSelectAction("paste_review")}
            className="cm-btn-secondary px-7 py-3.5 text-sm font-medium hover:border-[#7C8CFF]/50"
          >
            <Code2 className="w-5 h-5 text-[#7C8CFF]" />
            <span>Paste Code Snippet</span>
          </button>
        </div>
      </div>

      {/* 2. Interactive Holographic 3D Code Scanner Demonstration */}
      <div className="max-w-4xl mx-auto space-y-3">
        <div className="flex items-center justify-between text-xs font-mono text-[#9AA4B2] px-2">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-[#7C8CFF]" />
            <span className="font-semibold text-[#F4F7FB]">INTERACTIVE SCANNER DEMO</span>
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
              1. Detected Vulnerability
            </button>
            <button
              onClick={() => setActiveCodeTab("fixed")}
              className={`px-3 py-1 rounded text-[11px] font-semibold transition-all ${
                activeCodeTab === "fixed"
                  ? "bg-[#36D399]/15 text-[#36D399] border border-[#36D399]/30"
                  : "bg-[#10131A] text-[#687386] border border-[#232936]"
              }`}
            >
              2. Validated Patch
            </button>
          </div>
        </div>

        <Card3DTilt className="cm-card border-[#232936] bg-[#090B10] overflow-hidden text-left relative shadow-2xl">
          {/* Editor Header Bar */}
          <div className="h-9 px-4 bg-[#10131A] border-b border-[#232936] flex items-center justify-between font-mono text-xs text-[#687386]">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#FF5D73]" />
              <span className="w-2.5 h-2.5 rounded-full bg-[#F4C95D]" />
              <span className="w-2.5 h-2.5 rounded-full bg-[#36D399]" />
              <span className="ml-2 text-[#9AA4B2] font-semibold">server/routes/users.py</span>
            </div>
            <span className="text-[11px] text-[#7C8CFF] font-semibold">
              {activeCodeTab === "vulnerable" ? "AST FINDING (CWE-89)" : "PATCH CHECKS PASSED"}
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
                    SINK DETECTED
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
                    PARAMETERIZED
                  </span>
                </div>
                <div className="text-[#36D399]">    return db.execute(query, (user_id,))</div>
              </>
            )}
          </div>
        </Card3DTilt>
      </div>

      {/* 3. Out-Of-The-Box Bento Box Feature Grid */}
      <div className="space-y-4">
        <div className="text-center space-y-1">
          <h2 className="text-xs font-mono font-semibold text-[#7C8CFF] uppercase tracking-wider">
            SYSTEM ARCHITECTURE & CAPABILITIES
          </h2>
          <p className="text-lg font-bold text-[#F4F7FB]">
            Built for developers who value evidence over AI guesses.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 text-left">
          {/* Bento Card 1 */}
          <Card3DTilt className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-3">
            <div className="w-10 h-10 rounded-xl bg-[#FF5D73]/15 border border-[#FF5D73]/30 flex items-center justify-center text-[#FF5D73]">
              <Zap className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-[#F4F7FB]">Deterministic AST Scans</h3>
            <p className="text-xs text-[#9AA4B2] leading-relaxed">
              Static analysis rules inspect Python and JavaScript AST trees before AI review adds context.
            </p>
            <div className="text-[11px] font-mono text-[#36D399] pt-2 font-semibold">
              ✓ Rule-backed findings
            </div>
          </Card3DTilt>

          {/* Bento Card 2 */}
          <Card3DTilt className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-3">
            <div className="w-10 h-10 rounded-xl bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
              <Layers className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-[#F4F7FB]">Grounded Evidence Chain</h3>
            <p className="text-xs text-[#9AA4B2] leading-relaxed">
              Every finding traces exact data flows: Source → Variable → Expression → Execution Sink.
            </p>
            <div className="text-[11px] font-mono text-[#7C8CFF] pt-2 font-semibold">
              ✓ Call path grounding
            </div>
          </Card3DTilt>

          {/* Bento Card 3 */}
          <Card3DTilt className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-3">
            <div className="w-10 h-10 rounded-xl bg-[#36D399]/15 border border-[#36D399]/30 flex items-center justify-center text-[#36D399]">
              <Lock className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-[#F4F7FB]">Safe 5-Point Patch Verification</h3>
            <p className="text-xs text-[#9AA4B2] leading-relaxed">
              Fixes pass string hash uniqueness, target line matching, and overlap checks before mutation.
            </p>
            <div className="text-[11px] font-mono text-[#36D399] pt-2 font-semibold">
              ✓ Patch checks before apply
            </div>
          </Card3DTilt>
        </div>
      </div>
    </div>
  );
}
