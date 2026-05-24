"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { Sparkline } from "@/components/Sparkline";

interface LiveStatus {
  enabled: boolean;
  dry_run_mode: boolean;
  venue: string;
  last_tick_ts: string | null;
  last_reconciliation_status: string | null;
  last_equity_quote: number | null;
  peak_equity_quote: number;
  drawdown_pct: number | null;
}

interface AuditEntry {
  ts: string;
  decision_type: string;
  input_state: { equity?: number };
}

export default function LivePage() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [history, setHistory] = useState<number[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const s = await apiGet<LiveStatus>("/api/v1/live/status");
      setStatus(s);
      const entries = await apiGet<AuditEntry[]>("/api/v1/decision-audit/recent?decision_type=snapshot&limit=100");
      const equity = entries
        .map((e) => e.input_state?.equity)
        .filter((v): v is number => typeof v === "number")
        .reverse();
      setHistory(equity);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  async function stopRunner() {
    setBusy(true);
    try {
      await apiPost("/api/v1/live/stop", {});
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!status) return <div className="text-zinc-400">Loading…</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Live Runner</h1>
        <div className="flex gap-3 items-center">
          <StatusBadge active={status.enabled} label={status.enabled ? "ENABLED" : "stopped"} />
          <StatusBadge active={status.dry_run_mode} label={status.dry_run_mode ? "dry-run" : "LIVE"} />
          <span className="font-mono text-sm text-zinc-400">{status.venue}</span>
          <button
            onClick={stopRunner}
            disabled={busy || !status.enabled}
            className="px-3 py-1 bg-red-900 text-red-100 rounded hover:bg-red-800 disabled:opacity-50"
          >
            {busy ? "..." : "Stop"}
          </button>
        </div>
      </div>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Equity</h2>
        <div className="flex gap-6 text-sm">
          <div>
            <div className="text-zinc-500 text-xs">Last</div>
            <div className="font-mono">{status.last_equity_quote?.toFixed(2) ?? "—"}</div>
          </div>
          <div>
            <div className="text-zinc-500 text-xs">Peak</div>
            <div className="font-mono">{status.peak_equity_quote.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-zinc-500 text-xs">Drawdown</div>
            <div className={`font-mono ${status.drawdown_pct && status.drawdown_pct < -0.02 ? "text-red-400" : ""}`}>
              {status.drawdown_pct != null ? `${(status.drawdown_pct * 100).toFixed(2)}%` : "—"}
            </div>
          </div>
        </div>
        <Sparkline values={history} className="mt-2" />
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-2">Last Tick</h2>
        <div className="text-sm font-mono text-zinc-400">
          {status.last_tick_ts ?? "—"} → {status.last_reconciliation_status ?? "—"}
        </div>
      </section>
    </div>
  );
}
