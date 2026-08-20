import { useState } from "react";

const STORAGE_KEY = "code_master_ai_session_id";

function generateId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  // ponytail: good enough fallback for browsers without crypto.randomUUID, not cryptographically strong
  return "sess-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// Generates a random id on first use and persists it in localStorage so review
// history can be grouped server-side. Not an account/identity concept.
export default function useSessionId() {
  const [sessionId] = useState(() => {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const id = generateId();
    localStorage.setItem(STORAGE_KEY, id);
    return id;
  });
  return sessionId;
}

