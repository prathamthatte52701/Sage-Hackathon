import { useState } from "react";
import { useAuth } from "../context/AuthContext";

export default function EmailVerificationNotice() {
  const { user, verifyEmail, resendVerification, logout } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleVerify(event) {
    event.preventDefault();
    setError("");
    setInfo("");
    setBusy(true);
    try {
      await verifyEmail(token.trim());
      setInfo("Email verified. Loading your workspace...");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleResend() {
    setError("");
    setInfo("");
    setBusy(true);
    try {
      await resendVerification();
      setInfo("A new verification link has been sent to your email.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center text-[var(--sage-text-primary)]">
      <form
        onSubmit={handleVerify}
        className="w-[380px] space-y-4 rounded-xl border border-[var(--sage-border-subtle)] bg-[#0c120e] p-6"
      >
        <div>
          <p className="text-lg font-bold tracking-wide">CODE MASTER AI</p>
          <p className="mt-1 text-xs text-[var(--sage-text-muted)]">
            Verify your email to continue
          </p>
        </div>

        <p className="text-xs text-[var(--sage-text-muted)]">
          We sent a verification link to{" "}
          <span className="text-[var(--sage-text-secondary)]">{user?.email}</span>. Open it, or paste
          the token below.
        </p>

        <input
          type="text"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Verification token"
          className="sage-input w-full"
        />

        {error && <p className="text-xs text-red-400">{error}</p>}
        {info && <p className="text-xs text-emerald-400">{info}</p>}

        <button type="submit" disabled={busy} className="sage-button-primary w-full">
          {busy ? "Please wait..." : "Verify email"}
        </button>
        <button
          type="button"
          onClick={handleResend}
          disabled={busy}
          className="w-full text-center text-xs text-[var(--sage-text-muted)] hover:text-[var(--sage-text-secondary)]"
        >
          Resend verification email
        </button>
        <button
          type="button"
          onClick={() => logout()}
          className="w-full text-center text-xs text-[var(--sage-text-muted)] hover:text-[var(--sage-text-secondary)]"
        >
          Log out
        </button>
      </form>
    </div>
  );
}
