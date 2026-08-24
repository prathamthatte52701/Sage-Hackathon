import React, { useCallback, useEffect, useRef, useState } from "react";
import useSessionId from "./hooks/useSessionId";
import { useAuth } from "./context/AuthContext";
import AuthScreen from "./components/AuthScreen";
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
import HackerLens from "./components/HackerLens";
import BrutalAudit from "./components/BrutalAudit";
import BlastRadiusView from "./components/BlastRadiusView";
// V2_AUTOMATION_DISABLED:
// Automation is intentionally excluded from CODE MASTER AI V1.
// Preserve this code for the V2 automation workflow.
// import AutomationWorkspace from "./components/AutomationWorkspace";
import GuardWorkspace from "./components/GuardWorkspace";
import HistoryPanel from "./components/HistoryPanel";
import ToastNotification from "./components/ToastNotification";
import AmbientBackground from "./components/AmbientBackground";
import CodeEditor from "./components/CodeEditor";
import { buildPostFixResult, getAuthoritativeScore } from "./utils/postFixResult";
import { getSecurityFindings } from "./utils/securityFindings";
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
  getProject,
} from "./api/client";

const ACTIVE_PROJECT_KEY = "code_master_ai_active_project_id";
// V2_AUTOMATION_DISABLED:
// Automation is intentionally excluded from CODE MASTER AI V1.
// Preserve this code for the V2 automation workflow.
// const TERMINAL_AUTOMATION = new Set(["complete", "paused", "failed", "stopped"]);

export default function App() {
  const sessionId = useSessionId();
  const { user, loading: authLoading, enabled: authEnabled } = useAuth();
  const projectRequestRef = useRef(0);

  // Navigation State: "overview" | "findings" | "paste_review" | "projects" | "chat" | "architecture" | "history"
  const [activeTab, setActiveTab] = useState("projects");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // Active Project Data State
  const [projectBundle, setProjectBundle] = useState(null); // { id, project, score, sourceType }
  const [scanStage, setScanStage] = useState(null); // null | "reading" | "analyzing" | "scoring" | "done"
  const [scanError, setScanError] = useState(null);
  // V2_AUTOMATION_DISABLED:
  // Automation is intentionally excluded from CODE MASTER AI V1.
  // Preserve this code for the V2 automation workflow.
  // const [automationStatus, setAutomationStatus] = useState(null);
  // const [automationMinimized, setAutomationMinimized] = useState(false);
  // const [stoppingAutomation, setStoppingAutomation] = useState(false);
  // const [automationRefreshedKey, setAutomationRefreshedKey] = useState(null);
  const [newProjectConfirmOpen, setNewProjectConfirmOpen] = useState(false);

  // Toast Notification State
  const [toast, setToast] = useState(null); // { type: "error"|"success"|"info", title, message }

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

  const beginProjectRequest = useCallback(() => {
    projectRequestRef.current += 1;
    return projectRequestRef.current;
  }, []);

  const isCurrentProjectRequest = useCallback((requestId) => {
    return projectRequestRef.current === requestId;
  }, []);

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

  useEffect(() => {
    setSelectedFinding(null);
  }, [projectBundle?.project_id]);

  const refreshActiveProject = useCallback(async (projectId) => {
    if (!projectId) return;
    const requestId = beginProjectRequest();
    const fresh = await getProject(projectId);
    if (!isCurrentProjectRequest(requestId)) return;
    let scored = null;
    try {
      scored = await scoreProject(projectId);
    } catch {
      scored = null;
    }
    if (!isCurrentProjectRequest(requestId)) return;
    const securityFindings = getSecurityFindings(fresh);
    setProjectBundle((prev) => ({
      ...prev,
      id: projectId,
      project_id: projectId,
      name: fresh.project?.name || fresh.name || prev?.name || "Imported Project",
      project: fresh.project || fresh,
      files: fresh.files || [],
      security_findings: securityFindings,
      findings: securityFindings,
      score: scored || prev?.score || null,
    }));
  }, [beginProjectRequest, isCurrentProjectRequest]);

  useEffect(() => {
    const projectId = localStorage.getItem(ACTIVE_PROJECT_KEY);
    if (!projectId || projectBundle) return;
    refreshActiveProject(projectId).catch(() => {
      localStorage.removeItem(ACTIVE_PROJECT_KEY);
    });
  }, [projectBundle, refreshActiveProject]);

  // V2_AUTOMATION_DISABLED:
  // Automation is intentionally excluded from CODE MASTER AI V1.
  // Preserve this code for the V2 automation workflow.
  // Automation status polling is disabled in V1 runtime.

  useEffect(() => {
    const hasActiveWork = applyingFix || reanalyzing;
    if (!hasActiveWork) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "Analysis is still running. Leaving this page may interrupt the current view.";
      return event.returnValue;
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [applyingFix, reanalyzing]);

  // Project Import Handler
  const handleProjectUploaded = async (uploadData) => {
    const projId = uploadData.project_id || uploadData.id;
    if (!projId) return;

    setScanError(null);
    setScanStage("reading");
    const requestId = beginProjectRequest();

    try {
      localStorage.setItem(ACTIVE_PROJECT_KEY, projId);
      setSelectedFinding(null);
      setProjectBundle({
        id: projId,
        project_id: projId,
        name: uploadData.name || uploadData.repo_name || "Imported Project",
        project: uploadData.project?.project || uploadData.project || {},
        files: uploadData.project?.files || [],
        security_findings: [],
        findings: [],
        score: null,
      });

      setScanStage("analyzing");
      const analyzed = await analyzeProject(projId);
      if (!isCurrentProjectRequest(requestId)) return;
      const analyzedSecurityFindings = getSecurityFindings(analyzed);
      setProjectBundle((prev) => ({
        ...prev,
        project: analyzed.project || analyzed,
        files: analyzed.files || prev.files,
        security_findings: analyzedSecurityFindings,
        findings: analyzedSecurityFindings,
      }));
      setScanStage("scoring");
      let scored = null;
      try {
        scored = await scoreProject(projId);
      } catch {
        scored = null;
      }
      if (scored) {
        if (!isCurrentProjectRequest(requestId)) return;
        setProjectBundle((prev) => ({
          ...prev,
          score: scored,
        }));
      }
      setScanStage("done");
      if (!isCurrentProjectRequest(requestId)) return;
      setActiveTab("overview");
      refreshHistory();
      setToast({
        type: "success",
        title: "Defender Complete",
        message: "Project analysis finished. Review the overview and findings.",
      });
    } catch (err) {
      if (!isCurrentProjectRequest(requestId)) return;
      setScanError(err.message || "Project analysis failed.");
      setScanStage(null);
      setToast({
        type: "error",
        title: "Analysis Failed",
        message: err.message || "Could not analyze the project.",
      });
    }
  };

  const requestNewProject = () => {
    if (projectBundle) {
      setNewProjectConfirmOpen(true);
      return;
    }
    setActiveTab("projects");
  };

  const confirmNewProject = () => {
    localStorage.removeItem(ACTIVE_PROJECT_KEY);
    beginProjectRequest();
    setProjectBundle(null);
    setSelectedFinding(null);
    // V2_AUTOMATION_DISABLED:
    // Automation is intentionally excluded from CODE MASTER AI V1.
    // Preserve this code for the V2 automation workflow.
    // setAutomationStatus(null);
    // setAutomationMinimized(false);
    setReanalysisResult(null);
    setActiveFixData(null);
    setApplyingFix(false);
    setReanalyzing(false);
    setScanStage(null);
    setScanError(null);
    setNewProjectConfirmOpen(false);
    setActiveTab("projects");
  };

  const handleNavigation = (tab) => {
    if (tab === "projects" && projectBundle) {
      requestNewProject();
      return;
    }
    setActiveTab(tab);
  };

  // Reanalyze Active Project
  const handleReanalyzeProject = async () => {
    if (!projectBundle?.project_id || reanalyzing) return;
    const requestId = beginProjectRequest();
    setReanalyzing(true);
    try {
      const analyzed = await analyzeProject(projectBundle.project_id);
      if (!isCurrentProjectRequest(requestId)) return;
      const scored = await scoreProject(projectBundle.project_id);
      if (!isCurrentProjectRequest(requestId)) return;

      const analyzedSecurityFindings = getSecurityFindings(analyzed);
      setProjectBundle((prev) => ({
        ...prev,
        project: analyzed.project || analyzed,
        files: analyzed.files || prev.files,
        security_findings: analyzedSecurityFindings,
        findings: analyzedSecurityFindings,
        score: scored,
      }));

      setToast({
        type: "success",
        title: "Project Reanalyzed",
        message: "Updated project health score and static findings.",
      });
    } catch (err) {
      if (!isCurrentProjectRequest(requestId)) return;
      setToast({
        type: "error",
        title: "Reanalysis Failed",
        message: err.message || "Could not reanalyze the project.",
      });
    } finally {
      if (isCurrentProjectRequest(requestId)) setReanalyzing(false);
    }
  };

  // Fix All already runs its own server-side reanalysis before reporting
  // completion -- this just pulls the already-updated project + score into
  // local state, without triggering a second full analyze pass.
  const handleFixAllComplete = async () => {
    if (!projectBundle?.project_id) return;
    const requestId = beginProjectRequest();
    try {
      const fresh = await getProject(projectBundle.project_id);
      if (!isCurrentProjectRequest(requestId)) return;
      const scored = await scoreProject(projectBundle.project_id);
      if (!isCurrentProjectRequest(requestId)) return;
      const freshSecurityFindings = getSecurityFindings(fresh);
      setProjectBundle((prev) => ({
        ...prev,
        project: fresh.project || fresh,
        files: fresh.files || prev.files,
        security_findings: freshSecurityFindings,
        findings: freshSecurityFindings,
        score: scored,
      }));
    } catch (err) {
      if (!isCurrentProjectRequest(requestId)) return;
      setToast({
        type: "error",
        title: "Refresh Failed",
        message: err.message || "Fix All finished, but the project view could not be refreshed. Reload to see the latest state.",
      });
    }
  };

  // Generate Fix for a Finding (Specification §16)
  const handleGenerateFix = async (finding) => {
    if (!projectBundle?.project_id || !finding || generatingFix) return;
    setGeneratingFix(true);
    try {
      const data = await transformFinding(
        projectBundle.project_id,
        finding
      );

      setActiveFixData({
        finding,
        original_code: data.original_code,
        fixed_code: data.fixed_code,
        explanation: data.explanation,
        confidence: data.confidence,
        can_apply: data.can_apply,
        apply_failure_reason: data.apply_failure_reason,
        validation: data.validation,
      });
    } catch (err) {
      if (!isCurrentProjectRequest(requestId)) return;
      setToast({
        type: "error",
        title: "Fix Generation Failed",
        message: err.message || "Could not generate fix for this finding.",
      });
    } finally {
      setGeneratingFix(false);
    }
  };

  // Apply changes source once, then run the canonical analysis job on stored source.
  const handleApplyFix = async () => {
    if (!projectBundle?.project_id || !activeFixData || applyingFix) return;
    if (!activeFixData.can_apply || !Object.values(activeFixData.validation || {}).every(Boolean)) {
      setToast({
        type: "error",
        title: "Fix Is Not Applyable",
        message: "Regenerate the fix after resolving the failed patch validation check.",
      });
      return;
    }
    setApplyingFix(true);
    const requestId = beginProjectRequest();
    const beforeScore = getAuthoritativeScore(projectBundle.score);
    const beforeFindings = [...getSecurityFindings(projectBundle)];
    try {
      // Step 1: Apply the validated patch to stored source.
      await applyProjectFix(
        projectBundle.project_id,
        activeFixData.finding
      );
      if (!isCurrentProjectRequest(requestId)) return;

      // Step 2: Reanalyze the current stored source and refresh its score.
      let newAnalyzed;
      let newScored;
      try {
        newAnalyzed = await reanalyzeProject(projectBundle.project_id);
        if (!isCurrentProjectRequest(requestId)) return;
        newScored = await scoreProject(projectBundle.project_id);
        if (!isCurrentProjectRequest(requestId)) return;
      } catch (verificationErr) {
        let fresh = null;
        let scored = null;
        try {
          fresh = await getProject(projectBundle.project_id);
          if (!isCurrentProjectRequest(requestId)) return;
          scored = await scoreProject(projectBundle.project_id);
          if (!isCurrentProjectRequest(requestId)) return;
        } catch {
          // The source mutation already succeeded. Keep the popup honest even
          // if the verification refresh also fails.
        }
        setReanalysisResult(buildPostFixResult({
          beforeScore,
          afterScore: getAuthoritativeScore(scored),
          beforeFindings,
          afterFindings: getSecurityFindings(fresh),
          verificationStatus: "incomplete",
          error: verificationErr.message || "Fix applied, but reanalysis could not verify the result.",
        }));
        if (fresh || scored) {
          setProjectBundle((prev) => ({
            ...prev,
            project: fresh?.project || fresh || prev.project,
            files: fresh?.files || prev.files,
            security_findings: fresh ? getSecurityFindings(fresh) : getSecurityFindings(prev),
            findings: fresh ? getSecurityFindings(fresh) : getSecurityFindings(prev),
            score: scored || prev.score,
          }));
        }
        setActiveFixData(null);
        refreshHistory();
        setToast({
          type: "info",
          title: "Fix Applied",
          message: "Fix applied, but verification reanalysis did not complete.",
        });
        return;
      }

      const afterFindings = getSecurityFindings(newAnalyzed);
      setReanalysisResult(buildPostFixResult({
        beforeScore,
        afterScore: getAuthoritativeScore(newScored),
        beforeFindings,
        afterFindings,
        verificationStatus: "verified",
      }));

      setProjectBundle((prev) => ({
        ...prev,
        project: newAnalyzed.project || newAnalyzed,
        files: newAnalyzed.files || prev.files,
        security_findings: afterFindings,
        findings: afterFindings,
        score: newScored,
      }));

      setActiveFixData(null);
      refreshHistory();
      setToast({
        type: "success",
        title: "Fix Applied & Project Reanalyzed",
        message: "Fix applied and the current stored source was reanalyzed.",
      });
    } catch (err) {
      setToast({
        type: "error",
        title: "Fix Application Failed",
        message: err.message || "Could not apply fix safely.",
      });
    } finally {
      if (isCurrentProjectRequest(requestId)) setApplyingFix(false);
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
      setToast({
        type: "error",
        title: "Review Failed",
        message: err.message || "Could not review code snippet.",
      });
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
      setToast({
        type: "error",
        title: "Fix Failed",
        message: err.message || "Could not generate snippet fix.",
      });
    } finally {
      setSnippetFixing(false);
    }
  };

  if (authEnabled && authLoading) return null;
  if (authEnabled && !user) return <AuthScreen />;

  return (
    <div className="flex min-h-screen bg-[#090B10] text-[#F4F7FB] font-sans antialiased relative">
      <AmbientBackground />
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={(tab) => {
          handleNavigation(tab);
          setMobileSidebarOpen(false);
        }}
        project={projectBundle}
        hasFindings={Boolean(getSecurityFindings(projectBundle).length)}
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
                onSelectCategory={(_category) => {
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
                try {
                  const res = await reasonFinding(projectBundle.project_id, finding);
                  setToast({
                    type: "info",
                    title: "Reasoning Analysis",
                    message: res.reason || res.explanation || "AST & semantic evidence grounded.",
                  });
                } catch (err) {
                  setToast({
                    type: "error",
                    title: "Reasoning Failed",
                    message: err.message,
                  });
                }
              }}
              onFixAllComplete={handleFixAllComplete}
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
            />
          )}

          {/* View: Hacker Mode */}
          {activeTab === "hacker_lens" && (
            <HackerLens projectId={projectBundle?.project_id} />
          )}

          {/* View: Brutal Audit */}
          {activeTab === "brutal_audit" && (
            <BrutalAudit projectId={projectBundle?.project_id} project={projectBundle} />
          )}

          {/* View: Blast Radius */}
          {activeTab === "blast_radius" && (
            <BlastRadiusView projectId={projectBundle?.project_id} />
          )}

          {/* View: Commit Guard */}
          {activeTab === "commit_guard" && (
            <GuardWorkspace
              mode="commit"
              project={projectBundle}
            />
          )}

          {/* View: PR Guard */}
          {activeTab === "pr_guard" && (
            <GuardWorkspace
              mode="pr"
              project={projectBundle}
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

      {/* Modals & Toast Notifications */}
      {activeFixData && (
        <FixValidationModal
          fixData={activeFixData}
          onApply={handleApplyFix}
          onReject={() => setActiveFixData(null)}
          applying={applyingFix}
        />
      )}

      {/* Toast Notification Banner */}
      <ToastNotification toast={toast} onClose={() => setToast(null)} />

      {/* V2_AUTOMATION_DISABLED:
          Automation is intentionally excluded from CODE MASTER AI V1.
          Preserve this code for the V2 automation workflow.
          The AutomationWorkspace runtime widget is not mounted in V1. */}

      {newProjectConfirmOpen && (
        <div className="fixed inset-0 z-[60] bg-[#090B10]/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-xl border border-[#232936] bg-[#10131A] p-6 shadow-2xl space-y-5">
            <div>
              <h2 className="text-lg font-extrabold text-[#F4F7FB]">START A NEW PROJECT?</h2>
              <p className="mt-2 text-sm text-[#9AA4B2] leading-relaxed">
                Your current repository session contains analysis, fixes and generated reports. Starting a new project will leave this workspace and switch CODE MASTER AI to a new repository.
              </p>
              <p className="mt-3 text-xs text-[#F4C95D]">
                Make sure you have downloaded any hardened source or reports you want to keep.
              </p>
            </div>
            <div className="flex justify-end gap-3">
              <button type="button" onClick={() => setNewProjectConfirmOpen(false)} className="cm-btn-secondary text-xs">
                Cancel
              </button>
              <button type="button" onClick={confirmNewProject} className="cm-btn-primary text-xs">
                Start New Project
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reanalysis Confirmation Banner */}
      {reanalysisResult && (
        <div className="fixed bottom-6 right-6 z-40">
          <ReanalysisResult
            result={reanalysisResult}
            projectId={projectBundle?.project_id}
            onClose={() => setReanalysisResult(null)}
          />
        </div>
      )}
    </div>
  );
}
