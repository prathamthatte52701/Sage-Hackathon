import React, { useEffect, useState } from "react";
import api from "../api/client";

const label = (status) => String(status || "").replaceAll("_", " ").toUpperCase();

export default function SelfHealingWorkspace() {
  const [scenario, setScenario] = useState("schema_mismatch");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [runtimeLog, setRuntimeLog] = useState(JSON.stringify({
    workflow_name: "Order Processing",
    events: [{ step: "create_order", status: "failed", http_status: 400, error_type: "ValidationError", message: "Required field customer_id is missing", payload: { customerId: "cust_42" } }],
  }, null, 2));
  const [monitorResult, setMonitorResult] = useState(null);
  const [monitorBusy, setMonitorBusy] = useState(false);
  const [monitorError, setMonitorError] = useState("");

  const loadHistory = async () => {
    try { setHistory((await api.get("/api/workflows/history")).data.items || []); } catch { /* shown by run errors */ }
  };
  useEffect(() => { loadHistory(); }, []);

  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await api.post("/api/workflows/run", { scenario }, { timeout: 15000 });
      setResult(response.data);
      await loadHistory();
    } catch (err) { setError(err?.response?.data?.error || err?.response?.data?.detail || (err?.code === "ECONNABORTED" ? "The workflow request timed out." : "Could not reach the workflow API. Is the backend running?")); }
    finally { setBusy(false); }
  };

  const analyzeLogs = async () => {
    setMonitorError(""); setMonitorResult(null);
    let parsed;
    try { parsed = JSON.parse(runtimeLog); } catch { setMonitorError("Runtime events must be valid JSON."); return; }
    setMonitorBusy(true);
    try {
      const response = await api.post("/api/workflows/monitor", parsed, { timeout: 20000 });
      setMonitorResult(response.data);
      await loadHistory();
    } catch (err) { setMonitorError(err?.response?.data?.detail || err?.response?.data?.error || "Could not analyze these runtime events."); }
    finally { setMonitorBusy(false); }
  };

  return <div className="max-w-5xl mx-auto space-y-5">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><div className="text-[10px] font-mono tracking-[.2em] text-[#a6ff5b]">SAGE AI / RECOVERY LAB</div><h1 className="mt-2 text-2xl font-semibold">Self-healing workflow</h1><p className="mt-1 text-sm text-[#9AA4B2]">Run the bounded order-workflow demo, or analyze structured runtime events from another workflow.</p></div>
      <div className="flex gap-2"><select aria-label="Workflow scenario" className="rounded-lg border border-[#30383a] bg-[#101713] px-3 py-2 text-sm" value={scenario} onChange={(e) => setScenario(e.target.value)}><option value="schema_mismatch">Schema mismatch — recoverable</option><option value="invalid_credentials">Invalid credentials — escalate</option></select><button onClick={run} disabled={busy} className="rounded-lg bg-[#a6ff5b] px-4 py-2 text-sm font-semibold text-[#101510] disabled:opacity-50">{busy ? "Running…" : "Run demo workflow"}</button></div>
    </header>
    <section className="rounded-xl border border-white/10 bg-[#0d120f] p-4">
      <div className="mb-3"><h2 className="text-sm font-semibold">Monitor runtime events</h2><p className="mt-1 text-xs text-[#9AA4B2]">Paste redacted structured events from a real workflow. Sage will identify failures, explain the evidence, and validate only supported repair proposals.</p></div>
      <textarea aria-label="Runtime event JSON" value={runtimeLog} onChange={(event) => setRuntimeLog(event.target.value)} rows={8} className="w-full rounded-lg border border-white/10 bg-[#080c09] p-3 font-mono text-xs text-[#d2ddd3]" />
      <div className="mt-3 flex flex-wrap items-center gap-3"><button onClick={analyzeLogs} disabled={monitorBusy} className="rounded-lg border border-[#a6ff5b]/40 bg-[#a6ff5b]/10 px-4 py-2 text-xs font-semibold text-[#caff9a] disabled:opacity-50">{monitorBusy ? "Analyzing events…" : "Analyze runtime events"}</button><span className="text-[11px] text-[#778278]">Secrets are redacted. This endpoint analyzes evidence only; it does not connect to or replay an external workflow.</span></div>
      {monitorError && <p role="alert" className="mt-3 text-xs text-red-300">{monitorError}</p>}
      {monitorResult && <div className="mt-4 space-y-3 rounded-lg border border-white/10 bg-[#090d0a] p-4">
        <div className="flex flex-wrap justify-between gap-2"><div className="text-xs text-[#9AA4B2]">Event analysis {monitorResult.execution_id.slice(0, 8)} · {monitorResult.workflow_name}</div><span className="text-xs font-mono text-[#a6ff5b]">{monitorResult.status}</span></div>
        <div><div className="text-xs font-semibold">Likely cause</div><p className="mt-1 text-xs text-[#c5cec6]">{monitorResult.diagnosis.root_cause}</p><p className="mt-1 text-xs text-[#a6ff5b]">Recommended: {monitorResult.diagnosis.recommended_action}</p><p className="mt-1 text-[10px] text-[#778278]">Diagnosis source: {monitorResult.diagnosis.source}</p></div>
        <div className="grid gap-3 md:grid-cols-2"><div><div className="text-xs font-semibold">Repair safety validation: {label(monitorResult.repair_validation.status)}</div><p className="mt-1 text-xs text-[#9AA4B2]">{monitorResult.repair_validation.reason}</p></div><pre className="overflow-auto rounded bg-[#050705] p-2 text-[11px] text-[#b8c6ba]">{JSON.stringify({ proposed_payload: monitorResult.repair_validation.proposed_payload || null, retry_performed: monitorResult.retry_performed, human_approval: monitorResult.diagnosis.requires_human_approval }, null, 2)}</pre></div>
        <p className="border-t border-white/5 pt-2 text-[11px] text-amber-200">{monitorResult.message}</p>
      </div>}
    </section>
    {error && <div role="alert" className="rounded-lg border border-red-500/40 bg-red-950/30 p-3 text-sm text-red-200">{error}</div>}
    {!result && !busy && <div className="rounded-xl border border-white/10 bg-[#0d120f] p-5 text-sm text-[#9AA4B2]">Choose a scenario and run it to view evidence, diagnosis, safety validation, retry, and verification stages.</div>}
    {busy && <div className="rounded-xl border border-white/10 bg-[#0d120f] p-5 text-sm text-[#a6ff5b]">Executing workflow…</div>}
    {result && <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-[#0d120f] p-4"><div><div className="text-xs text-[#9AA4B2]">Execution {result.execution_id}</div><div className="mt-1 text-sm">{result.persistence === "process_memory_only" ? "History: in-memory on this server process" : "History: persisted"}</div></div><span className={`rounded-full px-3 py-1 text-xs font-mono ${result.status === "RECOVERED" ? "bg-emerald-900/50 text-emerald-300" : "bg-amber-900/50 text-amber-200"}`}>{result.status}</span></div>
      {result.diagnosis && <div className="grid gap-4 md:grid-cols-2"><div className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><h2 className="text-sm font-semibold">Failure and diagnosis</h2><p className="mt-3 text-sm">{result.diagnosis.root_cause}</p><p className="mt-2 text-xs text-[#9AA4B2]">{result.diagnosis.recommended_action}</p><p className="mt-3 text-[11px] text-[#a6ff5b]">{result.diagnosis.source === "deterministic_fallback" ? "DETERMINISTIC DEMO DIAGNOSIS — no LLM response claimed" : "AI diagnosis"}</p></div><div className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><h2 className="text-sm font-semibold">Payload and repair</h2><pre className="mt-3 overflow-auto text-xs text-[#b8c6ba]">{JSON.stringify({ original: result.original_payload || result.events?.[0]?.payload, repaired: result.repaired_payload || null, repair: result.diagnosis.repair }, null, 2)}</pre></div></div>}
      <div className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><h2 className="mb-3 text-sm font-semibold">Execution timeline</h2><ol className="space-y-2">{result.events?.map((event, index) => <li key={`${event.stage}-${index}`} className="flex gap-3 border-l border-[#39453a] pl-3"><span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#a6ff5b]"/><div className="min-w-0 flex-1"><div className="flex flex-wrap justify-between gap-2 text-xs"><strong>{label(event.stage)}</strong><span className="text-[#a6ff5b]">{label(event.status)}</span></div><p className="mt-1 break-words text-xs text-[#9AA4B2]">{event.message || event.reason || (event.operation ? `Validated ${event.operation}` : event.verified ? `Verified order ${event.order?.order_id}` : event.diagnosis?.root_cause) || "Stage completed"}</p></div></li>)}</ol></div>
    </section>}
    <section className="rounded-xl border border-white/10 bg-[#0d120f] p-4"><div className="mb-3 flex justify-between"><h2 className="text-sm font-semibold">Recent executions</h2><button onClick={loadHistory} className="text-xs text-[#a6ff5b]">Refresh</button></div>{history.length ? <div className="space-y-2">{history.map((item) => <div key={item.execution_id} className="flex flex-wrap justify-between gap-2 border-t border-white/5 pt-2 text-xs"><span className="font-mono text-[#aab5ab]">{item.execution_id.slice(0, 8)} · {item.scenario || item.workflow_name || "workflow demo"}</span><span>{item.status} · {new Date(item.started_at).toLocaleString()}</span></div>)}</div> : <p className="text-xs text-[#778278]">No runs yet. History is process-memory only; it clears when the backend restarts.</p>}</section>
  </div>;
}
