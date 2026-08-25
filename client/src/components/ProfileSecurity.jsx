import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { Mail, Shield, Key, AlertCircle, CheckCircle, Loader2 } from "lucide-react";

export default function ProfileSecurity() {
  const { user, updatePassword, enabled, logout } = useAuth();
  const [passwordForm, setPasswordForm] = useState({
    current_password: "",
    new_password: "",
    confirm_password: "",
  });
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  function formatDate(dateString) {
    if (!dateString) return "Unknown";
    try {
      return new Date(dateString).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch {
      return "Invalid date";
    }
  }

  async function handlePasswordChange(event) {
    event.preventDefault();
    setPasswordError("");
    setPasswordSuccess("");

    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordError("New passwords do not match");
      return;
    }

    if (passwordForm.new_password.length < 12) {
      setPasswordError("Password must be at least 12 characters");
      return;
    }

    if (passwordForm.current_password === passwordForm.new_password) {
      setPasswordError("New password must be different from current password");
      return;
    }

    setPasswordBusy(true);
    try {
      const result = await updatePassword(passwordForm.current_password, passwordForm.new_password);
      if (result?.password_changed) {
        setPasswordSuccess("Password updated successfully. Your other sessions have been revoked.");
        setPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
      } else {
        setPasswordError("Failed to update password");
      }
    } catch (err) {
      setPasswordError(err.message || "Failed to update password");
    } finally {
      setPasswordBusy(false);
    }
  }

  function handleInputChange(field, value) {
    setPasswordForm((prev) => ({ ...prev, [field]: value }));
    if (passwordError) setPasswordError("");
  }

  if (!enabled) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="cm-card p-6 border-[#232936] bg-[#10131A] text-center">
          <Shield className="w-12 h-12 mx-auto text-[#687386]" />
          <h3 className="mt-4 text-lg font-bold text-[#F4F7FB]">Profile Security</h3>
          <p className="mt-2 text-sm text-[#9AA4B2]">
            Profile security is available when authentication is enabled.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-bold text-[#F4F7FB]">Profile & Security</h2>
        <p className="text-sm text-[#9AA4B2]">
          Manage your account security settings, password, and active sessions.
        </p>
      </div>

      {/* Account Info Card */}
      <div className="cm-card border-[#232936] bg-[#10131A]">
        <div className="p-6 border-b border-[#232936]">
          <h3 className="text-lg font-bold text-[#F4F7FB] flex items-center gap-2">
            <Mail className="w-5 h-5 text-[#7C8CFF]" />
            Account Information
          </h3>
        </div>
        <div className="p-6 space-y-4">
          <div className="flex items-center gap-4 p-4 bg-[#090B10] rounded-lg border border-[#232936]">
            <div className="w-12 h-12 rounded-lg bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
              <Mail className="w-5 h-5" />
            </div>
            <div>
              <p className="text-xs text-[#9AA4B2]">Email Address</p>
              <p className="font-mono text-sm text-[#F4F7FB]">{user?.email || "Unknown"}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-[#090B10] rounded-lg border border-[#232936]">
              <p className="text-xs text-[#9AA4B2]">Email Verified</p>
              <div className="flex items-center gap-2 mt-1">
                {user?.email_verified ? (
                  <>
                    <CheckCircle className="w-5 h-5 text-[#36D399]" />
                    <span className="text-sm font-medium text-[#36D399]">Verified</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-5 h-5 text-[#F4C95D]" />
                    <span className="text-sm font-medium text-[#F4C95D]">Not Verified</span>
                  </>
                )}
              </div>
            </div>
            <div className="p-4 bg-[#090B10] rounded-lg border border-[#232936]">
              <p className="text-xs text-[#9AA4B2]">Account Created</p>
              <p className="font-mono text-sm text-[#F4F7FB] mt-1">{formatDate(user?.created_at)}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Password Change Card */}
      <div className="cm-card border-[#232936] bg-[#10131A]">
        <div className="p-6 border-b border-[#232936]">
          <h3 className="text-lg font-bold text-[#F4F7FB] flex items-center gap-2">
            <Key className="w-5 h-5 text-[#7C8CFF]" />
            Change Password
          </h3>
        </div>
        <div className="p-6 space-y-4">
          <p className="text-sm text-[#9AA4B2]">
            Changing your password will revoke all other active sessions. You will need to log in again on other devices.
          </p>

          {passwordError && (
            <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {passwordError}
            </div>
          )}

          {passwordSuccess && (
            <div className="p-4 rounded-lg bg-[#36D399]/10 border border-[#36D399]/30 text-[#36D399] text-sm flex items-center gap-2">
              <CheckCircle className="w-4 h-4 flex-shrink-0" />
              {passwordSuccess}
            </div>
          )}

          <form onSubmit={handlePasswordChange} className="space-y-4">
            <div>
              <label htmlFor="current_password" className="block text-sm font-medium text-[#F4F7FB] mb-1">
                Current Password
              </label>
              <div className="relative">
                <input
                  type={showCurrent ? "text" : "password"}
                  id="current_password"
                  autoComplete="current-password"
                  value={passwordForm.current_password}
                  onChange={(e) => handleInputChange("current_password", e.target.value)}
                  placeholder="Enter current password"
                  className="sage-input w-full pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowCurrent(!showCurrent)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#687386] hover:text-[#F4F7FB]"
                  aria-label={showCurrent ? "Hide password" : "Show password"}
                >
                  {showCurrent ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  )}
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="new_password" className="block text-sm font-medium text-[#F4F7FB] mb-1">
                New Password (min 12 characters)
              </label>
              <div className="relative">
                <input
                  type={showNew ? "text" : "password"}
                  id="new_password"
                  autoComplete="new-password"
                  value={passwordForm.new_password}
                  onChange={(e) => handleInputChange("new_password", e.target.value)}
                  placeholder="Enter new password"
                  className="sage-input w-full pr-10"
                  required
                  minLength={12}
                />
                <button
                  type="button"
                  onClick={() => setShowNew(!showNew)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#687386] hover:text-[#F4F7FB]"
                  aria-label={showNew ? "Hide password" : "Show password"}
                >
                  {showNew ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  )}
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="confirm_password" className="block text-sm font-medium text-[#F4F7FB] mb-1">
                Confirm New Password
              </label>
              <div className="relative">
                <input
                  type={showConfirm ? "text" : "password"}
                  id="confirm_password"
                  autoComplete="new-password"
                  value={passwordForm.confirm_password}
                  onChange={(e) => handleInputChange("confirm_password", e.target.value)}
                  placeholder="Confirm new password"
                  className="sage-input w-full pr-10"
                  required
                  minLength={12}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(!showConfirm)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#687386] hover:text-[#F4F7FB]"
                  aria-label={showConfirm ? "Hide password" : "Show password"}
                >
                  {showConfirm ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={passwordBusy}
              className="cm-btn-primary w-full py-2.5 text-sm"
            >
              {passwordBusy ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Updating...
                </span>
              ) : (
                "Update Password"
              )}
            </button>
          </form>
        </div>
      </div>

      {/* Sessions Link Card */}
      <div className="cm-card border-[#232936] bg-[#10131A]">
        <div className="p-6 border-b border-[#232936]">
          <h3 className="text-lg font-bold text-[#F4F7FB] flex items-center gap-2">
            <Shield className="w-5 h-5 text-[#7C8CFF]" />
            Active Sessions
          </h3>
        </div>
        <div className="p-6">
          <p className="text-sm text-[#9AA4B2] mb-4">
            View and manage your active sessions across all devices.
          </p>
          <button
            onClick={() => {
              // Navigate to sessions tab via URL hash or state
              window.location.href = "/#sessions";
            }}
            className="cm-btn-secondary w-full py-2.5 text-sm"
          >
            Manage Active Sessions
          </button>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="cm-card border-red-500/30 bg-red-500/5">
        <div className="p-6 border-b border-red-500/30">
          <h3 className="text-lg font-bold text-[#F4C95D] flex items-center gap-2">
            <AlertCircle className="w-5 h-5" />
            Danger Zone
          </h3>
        </div>
        <div className="p-6 space-y-4">
          <p className="text-sm text-[#F4C95D]">
            Irreversible actions. Proceed with caution.
          </p>
          <button
            onClick={() => {
              if (confirm("This will log you out of ALL devices. Are you sure?")) {
                logout();
              }
            }}
            className="cm-btn-destructive w-full py-2.5 text-sm"
          >
            Logout All Devices
          </button>
        </div>
      </div>
    </div>
  );
}