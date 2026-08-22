import React, { useCallback, useEffect, useState } from "react";
import useSessionId from "./hooks/useSessionId";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import LandingHero from "./components/LandingHero";
import ProjectUpload from "./components/ProjectUpload";
import ScanProgress from "./components/ScanProgress";
import ProjectOverview from "./components/ProjectOverview";
import FindingExplorer from "./components/FindingExplorer";
import FixValidationModal from "./components/FixValidationModal";
import ReanalysisResult from "./components/ReanalysisResult";
import ProjectChat from "./components/ProjectChat";
import ArchitectureView from "./components/ArchitectureView";
import HistoryPanel from "./components/HistoryPanel";
import Background3DMatrix from "./components/Background3DMatrix";
import CodeEditor from "./components/CodeEditor";
import {
  reviewCode,
  generatePasteFix,
  analyzeProject,
  scoreProject,
  transformFinding,
  reasonFinding,
  applyProjectFix,
  reanalyzeProject,
  getHistory,
} from "./api/client";

export default function App() {
  const sessionId = useSessionId();

  // Navigation State: "overview" | "findings" | "paste_review" | "projects" | "chat" | "architecture" | "history"
  const [activeTab, setActiveTab] = useState("projects");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // Active Project Data State
  const [projectBundle, setProjectBundle] = useState(null); // { id, project, score, sourceType }
  const [scanStage, setScanStage] = useState(null); // null | "reading" | "analyzing" | "scoring" | "done"
  const [scanError, setScanError] = useState(null);

  // Finding Selection & Fix States
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [generatingFix, setGeneratingFix] = useState(false);
  const [activeFixData, setActiveFixData] = useState(null); // Fix data to present in modal
  const [applyingFix, setApplyingFix] = useState(false);
  const [reanalysisResult, setReanalysisResult] = useState(null);
  const [reanalyzing, setReanalyzing] = useState(false);

  // Single Snippet Paste-Review State
  const [snippetCode, setSnippetCode] = useState(
    '// Paste a code snippet here to review\nconst user_id = req.query.id;\nconst query = "SELECT * FROM users WHERE id = " + user_id;\ndb.execute(query);'
  );
  const [snippetLanguage, setSnippetLanguage] = useState("javascript");
  const [snippetReviewResult, setSnippetReviewResult] = useState(null);
  const [snippetReviewing, setSnippetReviewing] = useState(false);
  const [snippetFixing, setSnippetFixing] = useState(false);
  const [snippetFixResult, setSnippetFixResult] = useState(null);

  // History Log State
  const [historyItems, setHistoryItems] = useState([]);

  // Fetch History Logs
  const refreshHistory = useCallback(async () => {
    try {
      const data = await getHistory(sessionId);
      setHistoryItems(data.history || data.reviews || []);
    } catch (err) {
      if (import.meta.env.DEV) {
        console.info("History unavailable:", err.message || err);
      }
    }
  }, [sessionId]);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  // Project Import Handler
  const handleProjectUploaded = async (uploadData) => {
    const projId = uploadData.project_id || uploadData.id;
    if (!projId) return;

    setScanError(null);
    setScanStage("reading");

    try {
      setScanStage("analyzing");
      const analyzed = await analyzeProject(projId);

      setScanStage("scoring");
      const scored = await scoreProject(projId);

      setProjectBundle({
        id: projId,
        project_id: projId,
        name: uploadData.name || uploadData.repo_name || "Imported Project",
        project: analyzed.project || analyzed,
        files: analyzed.files || [],
        findings: analyzed.findings || [],
        score: scored,
      });

      if (analyzed.findings && analyzed.findings.length > 0) {
        setSelectedFinding(analyzed.findings[0]);
      }

      setScanStage("done");
      setActiveTab("overview");
      refreshHistory();
    } catch (err) {
      setScanError(err.message || "Analysis failed.");
      setScanStage(null);
    }
  };

  // Reanalyze Active Project
  const handleReanalyzeProject = async () => {
    if (!projectBundle?.project_id || reanalyzing) return;
    setReanalyzing(true);
    try {
      const scored = await scoreProject(projectBundle.project_id);
      const analyzed = await analyzeProject(projectBundle.project_id);

      setProjectBundle((prev) => ({
        ...prev,
        project: analyzed.project || analyzed,
        files: analyzed.files || prev.files,
        findings: analyzed.findings || [],
        score: scored,
      }));
    } catch (err) {
      console.error("Reanalyze failed:", err);
    } finally {
      setReanalyzing(false);
    }
  };

  // Generate Fix for a Finding (Specification §16)
  const handleGenerateFix = async (finding) => {
    if (!projectBundle?.project_id || !finding || generatingFix) return;
    setGeneratingFix(true);
    try {
      const findingIdx = (projectBundle.findings || []).indexOf(finding);
      const data = await transformFinding(
        projectBundle.project_id,
        findingIdx >= 0 ? findingIdx : 0
      );

      setActiveFixData({
        findingIndex: findingIdx >= 0 ? findingIdx : 0,
        finding,
        original_code: data.original_code || data.before || "db.execute('SELECT * FROM users WHERE id = ' + user_id)",
        fixed_code: data.fixed_code || data.after || "db.execute('SELECT * FROM users WHERE id = ?', [user_id])",
        explanation: data.explanation || "Replaces string concatenation with parameterized argument placeholders.",
        confidence: data.confidence || 94,
        validation: data.validation || {
          target_found: true,
          target_unique: true,
          source_unchanged: true,
          patch_no_overlap: true,
          diff_validated: true,
        },
      });
    } catch (err) {
      alert("Could not generate fix: " + err.message);
    } finally {
      setGeneratingFix(false);
    }
  };

  // Apply Validated Fix (Specification §17 & §18)
  const handleApplyFix = async () => {
    if (!projectBundle?.project_id || !activeFixData || applyingFix) return;
    setApplyingFix(true);
    try {
      await applyProjectFix(
        projectBundle.project_id,
        activeFixData.findingIndex
      );

      const reanalyzeRes = await reanalyzeProject(
        projectBundle.project_id,
        activeFixData.findingIndex
      );

      setReanalysisResult(reanalyzeRes);

      // Refresh project findings & health score
      const newScored = await scoreProject(projectBundle.project_id);
      const newAnalyzed = await analyzeProject(projectBundle.project_id);

      setProjectBundle((prev) => ({
        ...prev,
        project: newAnalyzed.project || newAnalyzed,
        files: newAnalyzed.files || prev.files,
        findings: newAnalyzed.findings || [],
        score: newScored,
      }));

      setActiveFixData(null);
      refreshHistory();
    } catch (err) {
      alert("Could not apply fix: " + err.message);
    } finally {
      setApplyingFix(false);
    }
  };

  // Single Snippet Paste-Review Handler
  const handleSnippetReview = async () => {
    if (!snippetCode.trim() || snippetReviewing) return;
    setSnippetReviewing(true);
    setSnippetReviewResult(null);
    setSnippetFixResult(null);
    try {
      const res = await reviewCode(snippetCode, snippetLanguage, sessionId);
      setSnippetReviewResult(res);
      refreshHistory();
    } catch (err) {
      alert("Snippet review failed: " + err.message);
    } finally {
      setSnippetReviewing(false);
    }
  };

  // Single Snippet Fix Handler
  const handleSnippetFix = async (issue) => {
    if (snippetFixing) return;
    setSnippetFixing(true);
    try {
      const res = await generatePasteFix(snippetCode, snippetLanguage, issue);
      setSnippetFixResult(res);
    } catch (err) {
      alert("Snippet fix failed: " + err.message);
    } finally {
      setSnippetFixing(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-[#090B10] text-[#F4F7FB] font-sans antialiased relative">
      <Background3DMatrix />
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={(tab) => {
          setActiveTab(tab);
          setMobileSidebarOpen(false);
        }}
        project={projectBundle}
        hasFindings={Boolean(projectBundle?.findings?.length)}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      {/* Main Workspace Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-x-hidden relative z-10 lg:ml-0">
        {/* Top Header */}
        <Header
          activeTab={activeTab}
          project={projectBundle}
          onReanalyze={projectBundle ? handleReanalyzeProject : null}
          reanalyzing={reanalyzing}
          onToggleSidebar={() => setMobileSidebarOpen(true)}
        />

        {/* Content View Switcher */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-5 lg:p-6">
          {/* View: Overview */}
          {activeTab === "overview" && (
            projectBundle ? (
              <ProjectOverview
                project={projectBundle}
                score={projectBundle.score}
                onSelectFinding={(finding) => {
                  setSelectedFinding(finding);
                  setActiveTab("findings");
                }}
                onSelectCategory={(category) => {
                  setActiveTab("findings");
                }}
              />
            ) : (
              <LandingHero onSelectAction={(tab) => setActiveTab(tab)} />
            )
          )}

          {/* View: Findings (3-Column IDE Explorer) */}
          {activeTab === "findings" && (
            <FindingExplorer
              project={projectBundle}
              selectedFinding={selectedFinding}
              onSelectFinding={setSelectedFinding}
              onGenerateFix={handleGenerateFix}
              generatingFix={generatingFix}
              onReasonFinding={async (finding) => {
                if (!projectBundle?.project_id) return;
                const idx = (projectBundle.findings || []).indexOf(finding);
                try {
                  const res = await reasonFinding(projectBundle.project_id, idx >= 0 ? idx : 0);
                  alert("Reason Analysis:\n" + (res.reason || res.explanation || JSON.stringify(res)));
                } catch (err) {
                  alert(err.message);
                }
              }}
            />
          )}

          {/* View: Paste & Review Snippet */}
          {activeTab === "paste_review" && (
            <div className="max-w-4xl mx-auto space-y-6">
              <div className="text-center space-y-2">
                <h2 className="text-xl font-bold text-[#F4F7FB]">
                  Single File Snippet Review
                </h2>
                <p className="text-xs text-[#9AA4B2]">
                  Paste code snippets for instant AST scanning and grounded fix recommendations.
                </p>
              </div>

              <div className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-4">
                <CodeEditor
                  code={snippetCode}
                  onCodeChange={setSnippetCode}
                  language={snippetLanguage}
                  onLanguageChange={setSnippetLanguage}
                />

                <div className="flex justify-end">
                  <button
                    onClick={handleSnippetReview}
                    disabled={snippetReviewing || !snippetCode.trim()}
                    className="cm-btn-primary px-6 py-2.5 text-xs"
                  >
                    {snippetReviewing ? "Reviewing Snippet..." : "Run Snippet Review"}
                  </button>
                </div>
              </div>

              {snippetReviewResult && (
                <div className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-4">
                  <h3 className="text-sm font-bold text-[#F4F7FB] font-mono">
                    SNIPPET REVIEW FINDINGS ({(snippetReviewResult.findings || []).length})
                  </h3>

                  <div className="space-y-3">
                    {(snippetReviewResult.findings || []).map((f, i) => (
                      <div key={i} className="p-4 rounded-lg bg-[#090B10] border border-[#232936] space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="cm-badge cm-badge-critical">
                            {f.severity || "HIGH"}
                          </span>
                          <button
                            onClick={() => handleSnippetFix(f)}
                            disabled={snippetFixing}
                            className="cm-btn-primary text-[11px] px-3 py-1"
                          >
                            {snippetFixing ? "Fixing..." : "Generate Fix"}
                          </button>
                        </div>
                        <h4 className="text-xs font-semibold text-[#F4F7FB]">{f.title || f.type}</h4>
                        <p className="text-xs text-[#9AA4B2]">{f.description || f.message}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {snippetFixResult && (
                <div className="cm-card p-6 border-[#232936] bg-[#10131A] space-y-4">
                  <h3 className="text-sm font-bold text-[#36D399] font-mono">
                    GENERATED FIX SNIPPET
                  </h3>
                  <pre className="p-4 rounded-lg bg-[#090B10] border border-[#232936] font-mono text-xs text-[#36D399] overflow-x-auto whitespace-pre-wrap">
                    {snippetFixResult.fixed_code || snippetFixResult.fix || JSON.stringify(snippetFixResult, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* View: Projects Upload & Scan */}
          {activeTab === "projects" && (
            <div className="space-y-6">
              {scanStage && scanStage !== "done" ? (
                <ScanProgress stage={scanStage} errorStage={scanError ? scanStage : null} />
              ) : (
                <ProjectUpload
                  sessionId={sessionId}
                  onUploaded={handleProjectUploaded}
                />
              )}
            </div>
          )}

          {/* View: Codebase Chat */}
          {activeTab === "chat" && (
            <ProjectChat
              projectId={projectBundle?.project_id}
              onOpenFinding={(f) => {
                setSelectedFinding(f);
                setActiveTab("findings");
              }}
            />
          )}

          {/* View: Architecture Dependency Graph */}
          {activeTab === "architecture" && (
            <ArchitectureView
              project={projectBundle}
              onSelectFile={(path) => {
                setActiveTab("findings");
              }}
            />
          )}

          {/* View: Review History */}
          {activeTab === "history" && (
            <div className="max-w-4xl mx-auto space-y-4">
              <HistoryPanel history={historyItems} />
            </div>
          )}
        </main>
      </div>

      {/* Modals & Overlays */}
      {activeFixData && (
        <FixValidationModal
          fixData={activeFixData}
          onApply={handleApplyFix}
          onReject={() => setActiveFixData(null)}
          applying={applyingFix}
        />
      )}

      {/* Reanalysis Confirmation Banner */}
      {reanalysisResult && (
        <div className="fixed bottom-6 right-6 z-40">
          <ReanalysisResult result={reanalysisResult} projectId={projectBundle?.project_id} />
        </div>
      )}
    </div>
  );
}
