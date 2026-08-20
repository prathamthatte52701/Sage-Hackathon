import axios from "axios";

const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({ baseURL, timeout: 30000 });

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

export async function analyzeProject(projectId) {
  try {
    const res = await api.post(`/api/projects/${projectId}/analyze`, null, { timeout: 60000 });
    return res.data;
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

export async function transformFinding(projectId, findingIndex) {
  try {
    const res = await api.post(`/api/projects/${projectId}/findings/transform`, {
      finding_index: findingIndex,
    });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not generate a fix. Please try again."));
  }
}

export async function reasonFinding(projectId, findingIndex) {
  try {
    const res = await api.post(`/api/projects/${projectId}/findings/reason`, {
      finding_index: findingIndex,
    });
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

export async function reanalyzeProject(projectId, findingIndex) {
  try {
    const res = await api.post(`/api/projects/${projectId}/reanalyze`, {
      finding_index: findingIndex,
    });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not reanalyze the project. Please try again."));
  }
}

export async function applyProjectFix(projectId, findingIndex) {
  try {
    const res = await api.post(`/api/projects/${projectId}/fixes/apply`, {
      finding_index: findingIndex,
    });
    return res.data;
  } catch (err) {
    throw new Error(toFriendlyMessage(err, "Could not apply this fix safely."));
  }
}

export function fixedProjectZipUrl(projectId) {
  return `${baseURL}/api/projects/${projectId}/download-fixed`;
}

export default api;
