import { useState } from "react";
import { useAuth } from "../context/AuthContext";

export default function AuthScreen() {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await signup(email, password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center text-[var(--sage-text-primary)]">
      <form
        onSubmit={handleSubmit}
        className="w-[360px] space-y-4 rounded-xl border border-[var(--sage-border-subtle)] bg-[#0c120e] p-6"
      >
        <div>
          <p className="text-lg font-bold tracking-wide">CODE MASTER AI</p>
          <p className="mt-1 text-xs text-[var(--sage-text-muted)]">
            {mode === "login" ? "Sign in to continue" : "Create your account"}
          </p>
        </div>

        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="Email"
          className="sage-input w-full"
        />
        <input
          type="password"
          required
          minLength={8}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Password"
          className="sage-input w-full"
        />

        {error && <p className="text-xs text-red-400">{error}</p>}

        <button type="submit" disabled={busy} className="sage-button-primary w-full">
          {busy ? "Please wait..." : mode === "login" ? "Log in" : "Sign up"}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setError("");
          }}
          className="w-full text-center text-xs text-[var(--sage-text-muted)] hover:text-[var(--sage-text-secondary)]"
        >
          {mode === "login" ? "Need an account? Sign up" : "Already have an account? Log in"}
        </button>
      </form>
    </div>
  );
}
