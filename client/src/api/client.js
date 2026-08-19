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

export default api;
