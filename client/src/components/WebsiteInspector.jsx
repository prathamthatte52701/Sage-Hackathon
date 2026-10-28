import React, { useEffect, useState } from "react";
import { AlertTriangle, Globe, Loader2, Search } from "lucide-react";
import api from "../api/client";

const severityClass = {
  high: "border-red-500/30 bg-red-500/10 text-red-300",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  low: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  info: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
};

export default function WebsiteInspector({ project }) {
  const [url, setUrl] = useState("");
  const [logs, setLogs] = useState("");
  const [useSourceProject, setUseSourceProject] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");

  async function loadHistory() {
    try {
      const { data } = await api.get("/api/website-inspector/history");
      setHistory(data.items || []);
      setHistoryError(data.persistence?.includes("fallback") ? "MongoDB is unavailable; showing process-memory history." : "");
    } catch (err) { setHistoryError(err?.response?.data?.detail || "Could not load inspection history."); }
  }
  useEffect(() => { loadHistory(); }, []);

  async function inspect(event) {
    event.preventDefault();
    setError(""); setResult(null);
    let parsed;
    try { parsed = new URL(url.trim()); } catch { setError("Enter a valid website URL, including http:// or https://."); return; }
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) {
      setError("Only public HTTP/HTTPS website URLs without embedded credentials are supported."); return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/api/website-inspector/inspect", { url: parsed.href, logs: logs.trim() || undefined, source_project_id: useSourceProject ? project?.project_id : undefined }, { timeout: 45000 });
      setResult(data);
      await loadHistory();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.response?.data?.error || (err?.code === "ECONNABORTED" ? "Inspection timed out. The website may be slow or unreachable." : "Could not inspect that website. Check the URL and try again."));
    } finally { setBusy(false); }
  }

  return <div className="mx-auto max-w-5xl space-y-5">
    <header>
      <div className="flex items-center gap-2 text-[10px] font-mono tracking-[.2em] text-[#a6ff5b]"><Globe className="h-3.5 w-3.5"/> SAGE AI / WEBSITE INSPECTOR</div>
      <h1 className="mt-2 text-2xl font-semibold text-[#f3f7f2]">Inspect a live website</h1>
      <p className="mt-1 max-w-3xl text-sm text-[#9AA4B2]">Give Sage the deployed URL and its runtime logs. The URL shows what is failing; logs help explain why. Add the matching ZIP or repository to map stack-trace paths to source files.</p>
    </header>
    <form onSubmit={inspect} className="space-y-3 rounded-xl border border-white/10 bg-[#0d120f] p-4">
      <div className="flex flex-col gap-2 sm:flex-row"><input type="url" required maxLength={2048} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Deployed URL, e.g. https://your-app.example" aria-label="Website URL" className="min-w-0 flex-1 rounded-lg border border-white/10 bg-[#080c09] px-3 py-2.5 text-sm text-white placeholder:text-[#687386]" /><button type="submit" disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#a6ff5b] px-4 py-2.5 text-sm font-semibold text-[#101510] disabled:opacity-50">{busy ? <><Loader2 className="h-4 w-4 animate-spin"/> Inspecting…</> : <><Search className="h-4 w-4"/> Inspect Website</>}</button></div>
      <label className="block text-xs text-[#c5cec6]">Deployment/runtime logs <span className="text-[#778278]">(optional for website checks, needed for useful cause diagnosis)</span><textarea value={logs} onChange={(event) => setLogs(event.target.value.slice(0, 20000))} rows={7} placeholder={'Paste recent redacted deployment logs…\nExample: ModuleNotFoundError: No module named \'email_validator\''} className="mt-2 w-full rounded-lg border border-white/10 bg-[#080c09] p-3 font-mono text-xs text-[#d2ddd3] placeholder:text-[#687386]" /></label>
      <div className="flex flex-wrap items-center justify-between gap-3"><label className="cursor-pointer text-xs text-[#a6ff5b]"><input type="file" accept=".log,.txt,text/plain" className="hidden" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; if (file.size > 20000) { setError("Log file must be 20 KB or smaller."); return; } setLogs((await file.text()).slice(0, 20000)); setError(""); }} />Choose log file (.log/.txt)</label>
        {project?.project_id ? <label className="flex items-center gap-2 text-xs text-[#c5cec6]"><input type="checkbox" checked={useSourceProject} onChange={(event) => setUseSourceProject(event.target.checked)} />Map log stack frames to uploaded source: {project.name || "current project"}</label> : <span className="text-[11px] text-[#778278]">For file-level pinpointing, import the matching ZIP in Projects first.</span>}
      </div>
    </form>
    {error && <div role="alert" className="rounded-lg border border-red-500/30 bg-red-950/30 p-3 text-sm text-red-200"><AlertTriangle className="mr-2 inline h-4 w-4"/>{error}</div>}
    {busy && <div className="rounded-lg border border-white/10 bg-[#0d120f] p-4 text-sm text-[#a6ff5b]">Resolving a public address, fetching the page, and checking a limited set of internal links…</div>}
    {result && <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0d120f] p-4">
        <div className="min-w-0"><div className="text-xs text-[#9AA4B2]">Requested URL</div><div className="mt-1 break-all text-sm">{result.url}</div>{result.final_url !== result.url && <div className="mt-1 break-all text-xs text-[#9AA4B2]">Redirected to {result.final_url}</div>}</div>
        <div className="rounded-lg border border-white/10 px-3 py-2 text-sm"><span className={result.available ? "text-emerald-300" : "text-red-300"}>{result.available ? "AVAILABLE" : "HTTP ERROR"}</span><span className="ml-2 font-mono text-[#c6d0c7]">HTTP {result.http_status}</span></div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[["Page title", result.page_title || (result.html_inspected ? "Missing" : "Non-HTML response")], ["Content type", result.content_type || "Unknown"], ["Response size", `${result.response_bytes} bytes`], ["Same-site links checked", `${result.links_checked?.length || 0}${result.links_skipped ? ` (+${result.links_skipped} skipped)` : ""}`]].map(([name, value]) => <div key={name} className="rounded-lg border border-white/10 bg-[#0d120f] p-3"><div className="text-[11px] text-[#829086]">{name}</div><div className="mt-1 break-words text-sm text-[#eef3ee]">{value}</div></div>)}</div>
      <div className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Inspection findings</h2><span className="text-[11px] text-[#829086]">HTTP / HTML evidence</span></div><div className="space-y-3">{result.issues?.map((issue, index) => <article key={`${issue.title}-${index}`} className="rounded-lg border border-white/5 bg-[#090d0a] p-3"><div className="flex flex-wrap items-center gap-2"><span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${severityClass[issue.severity] || severityClass.info}`}>{issue.severity}</span><span className="text-sm font-medium">{issue.title}</span><span className="ml-auto text-[10px] text-[#829086]">{issue.verified ? "Verified from response" : "Potential issue"}</span></div><p className="mt-2 text-xs text-[#c5cec6]">{issue.description}</p><p className="mt-2 break-all font-mono text-[11px] text-[#829086]">Evidence: {issue.evidence}</p><p className="mt-2 text-xs text-[#a6ff5b]">Suggested action: {issue.recommended_action}</p></article>)}</div></div>
      {result.links_checked?.length > 0 && <div className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><h2 className="mb-2 text-sm font-semibold">Internal link sample</h2><div className="space-y-1.5">{result.links_checked.map((link) => <div key={link.url} className="flex flex-wrap justify-between gap-2 text-xs"><span className="break-all text-[#aeb9af]">{link.url}</span><span className={link.error || link.status >= 400 ? "text-red-300" : "text-emerald-300"}>{link.error || `HTTP ${link.status}`}</span></div>)}</div></div>}
      {result.log_diagnosis && <div className="rounded-xl border border-[#a6ff5b]/20 bg-[#0d120f] p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">Likely cause from runtime logs</h2><span className="text-[10px] font-mono uppercase text-[#a6ff5b]">{result.log_diagnosis.source} · {result.log_diagnosis.confidence} confidence</span></div><p className="mt-3 text-sm text-[#e5ebe5]">{result.log_diagnosis.likely_cause}</p><p className="mt-1 text-[11px] text-[#829086]">{result.log_diagnosis.source_scope}</p>{result.log_diagnosis.evidence?.length > 0 && <div className="mt-3"><div className="text-[11px] font-semibold text-[#c5cec6]">Log evidence (secrets redacted)</div><pre className="mt-1 overflow-auto whitespace-pre-wrap rounded bg-[#080c09] p-2 text-[11px] text-[#aab5ab]">{result.log_diagnosis.evidence.join("\n")}</pre></div>}<ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-[#a6ff5b]">{result.log_diagnosis.recommended_actions?.map((action, index) => <li key={index}>{action}</li>)}</ul><p className="mt-3 text-[11px] text-amber-200">Recommendation only. No changes were applied to the deployed site.</p></div>}
      {result.source_mapping && <div className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><h2 className="text-sm font-semibold">Source pinpointing</h2>{result.source_matches?.length ? result.source_matches.map((match) => <p key={`${match.path}:${match.line}`} className="mt-2 font-mono text-xs text-[#a6ff5b]">{match.path}:{match.line} — {match.evidence}</p>) : <p className="mt-2 text-xs text-[#9AA4B2]">{result.source_mapping_note || "No matching stack-frame paths found in the selected source project."}</p>}</div>}
      <p className="text-[11px] text-[#718075]">{result.inspection_scope} History: {result.persistence === "mongodb" ? "saved in MongoDB" : "stored in process memory and cleared on backend restart"}.</p>
    </section>}
    <section className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Recent inspections</h2><button type="button" onClick={loadHistory} className="text-xs text-[#a6ff5b]">Refresh</button></div>{historyError && <p className="mb-2 text-xs text-amber-200">{historyError}</p>}{history.length ? <div className="space-y-2">{history.map((item) => <button type="button" key={item.inspection_id} onClick={() => { setResult(item); setUrl(item.url); }} className="flex w-full flex-wrap justify-between gap-2 border-t border-white/5 pt-2 text-left text-xs hover:text-[#a6ff5b]"><span className="max-w-[75%] truncate">{item.url}</span><span>{item.http_status} · {new Date(item.inspected_at).toLocaleString()}</span></button>)}</div> : <p className="text-xs text-[#778278]">No website inspections yet.</p>}</section>
  </div>;
}
