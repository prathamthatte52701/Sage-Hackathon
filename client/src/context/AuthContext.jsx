import { createContext, useContext, useEffect, useState } from "react";
import api, {
  getMe,
  login as apiLogin,
  logout as apiLogout,
  resendVerification as apiResendVerification,
  signup as apiSignup,
  verifyEmail as apiVerifyEmail,
  getSessions,
  revokeSession,
  logoutAll,
  forgotPassword,
  resetPassword,
  changePassword,
} from "../api/client";

const AuthContext = createContext(null);
const demoUser = { id: "demo-user", email: "demo@sage.local", email_verified: true, demo_mode: true };

export function AuthProvider({ children, enabled = import.meta.env.VITE_AUTH_ENABLED === "true" }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!enabled) {
      setUser(demoUser);
      setLoading(false);
      return undefined;
    }

    getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));

    // Any request that comes back 401 mid-session (expired/invalid cookie)
    // means the client's belief that it's logged in is stale -- clear it so
    // the UI drops back to the login screen instead of showing a broken app.
    const interceptor = api.interceptors.response.use(
      (res) => res,
      (err) => {
        if (err?.response?.status === 401) setUser(null);
        return Promise.reject(err);
      }
    );
    return () => api.interceptors.response.eject(interceptor);
  }, [enabled]);

  async function login(email, password) {
    if (!enabled) return demoUser;
    const loggedInUser = await apiLogin(email, password);
    setUser(loggedInUser);
    return loggedInUser;
  }

  async function signup(email, password) {
    if (!enabled) return demoUser;
    const newUser = await apiSignup(email, password);
    setUser(newUser);
    return newUser;
  }

  async function logout() {
    if (!enabled) return;
    await apiLogout();
    setUser(null);
  }

  // Refresh the current user record (e.g. after email verification completes).
  async function refresh() {
    if (!enabled) return demoUser;
    try {
      const refreshed = await getMe();
      setUser(refreshed);
      return refreshed;
    } catch {
      setUser(null);
      return null;
    }
  }

  async function verifyEmail(token) {
    const result = await apiVerifyEmail(token);
    await refresh();
    return result;
  }

  async function resendVerification() {
    return apiResendVerification();
  }

  async function fetchSessions() {
    if (!enabled) return [];
    return getSessions();
  }

  async function revokeSessionById(sessionId) {
    if (!enabled) return;
    return revokeSession(sessionId);
  }

  async function logoutAllDevices() {
    if (!enabled) return;
    const result = await logoutAll();
    setUser(null);
    return result;
  }

  async function requestPasswordReset(email) {
    if (!enabled) return;
    return forgotPassword(email);
  }

  async function resetUserPassword(token, password) {
    if (!enabled) return;
    return resetPassword(token, password);
  }

  async function updatePassword(currentPassword, newPassword) {
    if (!enabled) return;
    return changePassword(currentPassword, newPassword);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        signup,
        logout,
        refresh,
        verifyEmail,
        resendVerification,
        fetchSessions,
        revokeSessionById,
        logoutAllDevices,
        requestPasswordReset,
        resetUserPassword,
        updatePassword,
        enabled,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
