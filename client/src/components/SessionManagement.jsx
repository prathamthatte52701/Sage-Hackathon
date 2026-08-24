import React, { useCallback, useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { LogOut, Trash2, Monitor, Smartphone, HelpCircle, AlertTriangle } from "lucide-react";

export default function SessionManagement() {
  const { fetchSessions, revokeSessionById, logoutAllDevices, logout, enabled } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revoking, setRevoking] = useState(null);
  const [logoutAllConfirm, setLogoutAllConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadSessions = useCallback(async () => {
    if (!enabled) return;
    try {
      setLoading(true);
      const data = await fetchSessions();
      setSessions(data.sessions || []);
    } catch (err) {
      setError(err.message || "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, [enabled, fetchSessions]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  async function handleRevoke(sessionId, isCurrent) {
    if (!confirm(`Revoke this session?${isCurrent ? " You will be logged out." : ""}`)) return;
    setRevoking(sessionId);
    try {
      const result = await revokeSessionById(sessionId);
      if (result?.revoked_current) {
        await logout();
      }
      await loadSessions();
    } catch (err) {
      setError(err.message || "Failed to revoke session");
    } finally {
      setRevoking(null);
    }
  }

  async function handleLogoutAll() {
    if (!confirm("This will log you out of ALL devices. Are you sure?")) return;
    setBusy(true);
    try {
      await logoutAllDevices();
    } catch (err) {
      setError(err.message || "Failed to log out all devices");
      setBusy(false);
    }
  }

  function formatDate(dateString) {
    if (!dateString) return "Unknown";
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return "Invalid date";
    }
  }

  function getDeviceIcon(deviceLabel) {
    if (!deviceLabel) return <Monitor className="w-4 h-4" />;
    if (deviceLabel.includes("Mobile")) return <Smartphone className="w-4 h-4" />;
    return <Monitor className="w-4 h-4" />;
  }

  if (!enabled) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="cm-card p-6 border-[#232936] bg-[#10131A] text-center">
          <HelpCircle className="w-12 h-12 mx-auto text-[#687386]" />
          <h3 className="mt-4 text-lg font-bold text-[#F4F7FB]">Session Management</h3>
          <p className="mt-2 text-sm text-[#9AA4B2]">
            Session management is available when authentication is enabled.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#F4F7FB]">Active Sessions</h2>
          <p className="text-sm text-[#9AA4B2]">
            Manage your logged-in devices. Revoke sessions you no longer use.
          </p>
        </div>
        <button
          onClick={() => setLogoutAllConfirm(true)}
          disabled={busy || revoking}
          className="cm-btn-destructive text-sm px-4 py-2"
        >
          <LogOut className="w-4 h-4 mr-2" />
          Logout All Devices
        </button>
      </div>

      {error && (
        <div className="cm-card p-4 border-red-500/30 bg-red-500/10 text-red-400 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      <div className="cm-card border-[#232936] bg-[#10131A] overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-[#687386]">
            <div className="animate-spin w-6 h-6 border-2 border-[#7C8CFF] border-t-transparent rounded-full mx-auto" />
            <p className="mt-3 text-sm">Loading sessions...</p>
          </div>
        ) : sessions.length === 0 ? (
          <div className="p-8 text-center text-[#687386]">
            <HelpCircle className="w-12 h-12 mx-auto text-[#687386]" />
            <p className="mt-3 text-sm">No active sessions found</p>
          </div>
        ) : (
          <div className="divide-y divide-[#232936]">
            {sessions.map((session) => (
              <div
                key={session.session_id}
                className="p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
              >
                <div className="flex items-center gap-4 min-w-0 flex-1">
                  <div className="w-10 h-10 rounded-lg bg-[#151922] border border-[#232936] flex items-center justify-center flex-shrink-0">
                    {getDeviceIcon(session.device_label)}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-[#F4F7FB] truncate block sm:inline">
                        {session.device_label || "Unknown device"}
                      </span>
                      {session.is_current && (
                        <span className="text-[10px] font-mono text-[#36D399] bg-[#36D399]/10 border border-[#36D399]/30 px-2 py-0.5 rounded">
                          Current
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-4 mt-1 text-xs text-[#9AA4B2]">
                      <span>
                        Created: <span className="font-mono text-[#687386]">{formatDate(session.created_at)}</span>
                      </span>
                      <span>
                        Last active: <span className="font-mono text-[#687386]">{formatDate(session.last_seen_at)}</span>
                      </span>
                      <span>
                        Expires: <span className="font-mono text-[#687386]">{formatDate(session.expires_at)}</span>
                      </span>
                    </div>
                  </div>
                </div>

                {!session.is_current && (
                  <button
                    onClick={() => handleRevoke(session.session_id, false)}
                    disabled={revoking === session.session_id}
                    className="cm-btn-destructive text-sm px-3 py-1.5 flex-shrink-0 whitespace-nowrap"
                  >
                    {revoking === session.session_id ? (
                      <span className="flex items-center gap-1.5">
                        <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                        Revoking...
                      </span>
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {logoutAllConfirm && (
        <div className="fixed inset-0 z-[60] bg-[#090B10]/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-xl border border-[#232936] bg-[#10131A] p-6 shadow-2xl space-y-5">
            <div>
              <h2 className="text-lg font-extrabold text-[#F4F7FB] flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-[#F4C95D]" />
                LOG OUT ALL DEVICES?
              </h2>
              <p className="mt-2 text-sm text-[#9AA4B2] leading-relaxed">
                This will immediately revoke <strong className="text-[#F4F7FB]">{sessions.length}</strong> active session{ sessions.length !== 1 ? "s" : "" } across all your devices.
              </p>
              <p className="mt-3 text-xs text-[#F4C95D]">
                You will need to log in again on every device.
              </p>
            </div>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setLogoutAllConfirm(false)}
                disabled={busy}
                className="cm-btn-secondary text-xs"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleLogoutAll}
                disabled={busy}
                className="cm-btn-destructive text-xs"
              >
                {busy ? "Logging out..." : "Yes, Logout All"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}