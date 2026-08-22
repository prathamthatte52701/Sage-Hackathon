import { createContext, useContext, useEffect, useState } from "react";
import api, { getMe, login as apiLogin, logout as apiLogout, signup as apiSignup } from "../api/client";

const AuthContext = createContext(null);
const demoUser = { id: "demo-user", email: "demo@sage.local", demo_mode: true };

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

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout, enabled }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
