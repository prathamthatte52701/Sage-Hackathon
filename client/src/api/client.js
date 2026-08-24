import axios from "axios";

const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// withCredentials: true is required so the HttpOnly session cookie set by
// /api/auth/login is actually sent on every subsequent request -- without
// it the browser drops the cookie on cross-origin requests (client :5173,
// server :8000 in dev) and every protected endpoint would 401.
// Backend's call_groq() budget is 2 attempts x 10s + backoff (~20.5s worst
// case), and every AI endpoint here retries once on a malformed-JSON
// response (a second full call_groq), so the real backend worst case for
// one AI-backed request is ~41s. This default must stay comfortably above
// that -- see server/services/groq_client.py for the backend side of this
// contract.
const api = axios.create({ baseURL, timeout: 45000, withCredentials: true });

// Extracts a human-readable message from any axios error shape we might get back:
// backend's {error: string}, FastAPI/Pydantic's {detail: ...}, network failure, or unknown.
function toFriendlyMessage(err, fallback) {
  const data = err?.response?.data;
  if (typeof data?.error === "string") return data.error;
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail) && data.detail[0]?.msg) {
    return data.detail.map((d) => d.msg).join("; ");
  }
  if (err?.code === "ECONNABORTED") return "The request timed out. Please try again.";
  if (!err?.response) return "Could not reach the server. Is the backend running?";
  return fallback;
}

export async function signup(email, password) {
  try {
    return (await api.post("/api/auth/signup", { email, password })).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not create account. Please try again."));
  }
}

export async function login(email, password) {
  try {
    return (await api.post("/api/auth/login", { email, password })).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Login failed. Please try again."));
  }
}

export async function logout() {
  try {
    await api.post("/api/auth/logout");
  } catch {
    // Logout is best effort; the local auth state is cleared regardless.
  }
}

export async function getMe() {
  return (await api.get("/api/auth/me")).data;
}

export async function verifyEmail(token) {
  try {
    return (await api.post("/api/auth/verify-email", { token })).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not verify your email."));
  }
}

export async function resendVerification() {
  try {
    return (await api.post("/api/auth/resend-verification", {})).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not resend the verification email."));
  }
}

export async function getSessions() {
  try {
    return (await api.get("/api/auth/sessions")).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load sessions."));
  }
}

export async function revokeSession(sessionId) {
  try {
    return (await api.delete(`/api/auth/sessions/${sessionId}`)).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not revoke session."));
  }
}

export async function logoutAll() {
  try {
    return (await api.post("/api/auth/logout-all")).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not log out all devices."));
  }
}

export async function reviewCode(code, language, sessionId) {
  try {
    const res = await api.post("/api/review", { code, language, session_id: sessionId });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Review failed. Please try again."));
  }
}

export async function generatePasteFix(code, language, issue) {
  try {
    const res = await api.post("/api/review/fix", { code, language, issue }, { timeout: 30000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not generate a fix. Please try again."));
  }
}

export async function explainIssue(issue, codeContext, language) {
  try {
    const res = await api.post("/api/explain-bug", {
      issue,
      code_context: codeContext,
      language,
    });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not get an explanation. Please try again."));
  }
}

export async function getHistory(sessionId) {
  try {
    const res = await api.get("/api/reviews/history", { params: { session_id: sessionId } });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load history. Please try again."));
  }
}

export async function uploadProject(file, sessionId, onUploadProgress) {
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);
    const res = await api.post("/api/projects/upload", formData, {
      timeout: 60000,
      onUploadProgress,
    });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Project upload failed. Please try again."));
  }
}

export async function importFromGithub(repoUrl, sessionId) {
  try {
    const res = await api.post(
      "/api/projects/github",
      { repo_url: repoUrl, session_id: sessionId },
      { timeout: 60000 }
    );
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not import this repository. Please try again."));
  }
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

async function waitForAnalysisJob(jobId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = (await api.get(`/api/analysis-jobs/${jobId}`)).data;
    if (job.status === "completed" || job.status === "partial") return job;
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(job.error || "Project analysis did not complete.");
    }
    await sleep(1000);
  }
  throw new Error("Project analysis is still running. Please refresh in a moment.");
}

export async function getProject(projectId) {
  try {
    return (await api.get(`/api/projects/${projectId}`)).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load project results."));
  }
}

export async function analyzeProject(projectId) {
  try {
    const { data } = await api.post(`/api/projects/${projectId}/analyze`, null);
    await waitForAnalysisJob(data.job_id);
    return await getProject(projectId);
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Project analysis failed. Please try again."));
  }
}

export async function scoreProject(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/score`, null, { timeout: 60000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Scoring failed. Please try again."));
  }
}

function findingReference(finding) {
  if (typeof finding === "object" && finding !== null) {
    if (!finding.finding_id) {
      throw new Error("This finding is missing its stable ID. Reanalyze the project and try again.");
    }
    return { finding_id: finding.finding_id };
  }
  return { finding_index: finding };
}

export async function getProjectFile(projectId, filePath) {
  try {
    return (await api.get(`/api/projects/${projectId}/files/${encodeURIComponent(filePath)}`)).data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load this project file."));
  }
}

export async function transformFinding(projectId, finding) {
  try {
    const res = await api.post(`/api/projects/${projectId}/findings/transform`, findingReference(finding));
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not generate a fix. Please try again."));
  }
}

export async function reasonFinding(projectId, finding) {
  try {
    const res = await api.post(`/api/projects/${projectId}/findings/reason`, findingReference(finding));
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not explain this finding. Please try again."));
  }
}

export async function chatAboutProject(projectId, question) {
  try {
    const res = await api.post(`/api/projects/${projectId}/chat`, { question }, { timeout: 30000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not answer that question. Please try again."));
  }
}

export async function reanalyzeProject(projectId) {
  try {
    const { data } = await api.post(`/api/projects/${projectId}/reanalyze`, {});
    await waitForAnalysisJob(data.job_id);
    return await getProject(projectId);
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not reanalyze the project. Please try again."));
  }
}

export async function applyProjectFix(projectId, finding) {
  try {
    const res = await api.post(`/api/projects/${projectId}/fixes/apply`, findingReference(finding));
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not apply this fix safely."));
  }
}

export function fixedProjectZipUrl(projectId) {
  return `${baseURL}/api/projects/${projectId}/download-fixed`;
}

export async function startFixAll(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/fix-all`, {});
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not start Fix All. Please try again."));
  }
}

export async function getFixAllStatus(projectId) {
  try {
    const res = await api.get(`/api/projects/${projectId}/fix-all/status`);
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load Fix All progress."));
  }
}

export async function stopFixAll(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/fix-all/stop`, {});
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not stop Fix All."));
  }
}

export async function runHackerLens(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/hacker-lens`, {}, { timeout: 60000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Hacker Mode analysis failed. Please retry."));
  }
}

export async function runBrutalAudit(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/brutal-audit`, {}, { timeout: 60000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Brutal Audit failed. Please retry."));
  }
}

export async function getBlastRadius(projectId) {
  try {
    const res = await api.get(`/api/projects/${projectId}/blast-radius`, { timeout: 60000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Blast Radius analysis failed. Please retry."));
  }
}

// V2_AUTOMATION_DISABLED:
// Automation is intentionally excluded from CODE MASTER AI V1.
// Preserve this code for the V2 automation workflow.
// export async function startAutomation(projectId) {
//   try {
//     const res = await api.post(`/api/projects/${projectId}/automation`, {}, { timeout: 30000 });
//     return res.data;
//   } catch (err) {
//     throw new Error(toFriendlyMessage(err, "Could not start automation."));
//   }
// }
//
// export async function getAutomationStatus(projectId, options = {}) {
//   try {
//     const res = await api.get(`/api/projects/${projectId}/automation/status`, { timeout: 30000 });
//     return res.data;
//   } catch (err) {
//     if (options.allowMissing && err?.response?.status === 404) return null;
//     throw new Error(toFriendlyMessage(err, "Could not load automation status."));
//   }
// }
//
// export async function stopAutomation(projectId) {
//   try {
//     const res = await api.post(`/api/projects/${projectId}/automation/stop`, {}, { timeout: 30000 });
//     return res.data;
//   } catch (err) {
//     throw new Error(toFriendlyMessage(err, "Could not stop automation."));
//   }
// }

export async function startCommitGuard(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/commit-guard`, {}, { timeout: 30000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not start Commit Guard."));
  }
}

export async function getCommitGuardStatus(projectId) {
  try {
    const res = await api.get(`/api/projects/${projectId}/commit-guard/status`, { timeout: 30000 });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load Commit Guard status."));
  }
}

export async function startPrGuard(projectId, pullRequestNumber) {
  try {
    const res = await api.post(
      `/api/projects/${projectId}/pr-guard`,
      { pull_request_number: Number(pullRequestNumber) },
      { timeout: 30000 }
    );
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not start PR Guard."));
  }
}

export async function getPrGuardStatus(projectId, runId, pullRequestNumber) {
  try {
    const res = runId
      ? await api.get(`/api/projects/${projectId}/pr-guard/${runId}/status`, { timeout: 30000 })
      : await api.get(`/api/projects/${projectId}/pr-guard/status`, {
          params: { pull_request_number: Number(pullRequestNumber) },
          timeout: 30000,
        });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not load PR Guard status."));
  }
}

export default api;
