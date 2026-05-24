"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

interface AuditEntry {
  id: string;
  ts: string;
  decision_type: string;
  input_state: { equity?: number; cash?: number; peak?: number };
  reconciliation_status: string;
}

export default function TicksPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await apiGet<AuditEntry[]>(
        "/api/v1/decision-audit/recent?decision_type=snapshot&limit=200",
      );
      setEntries(data);
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

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!entries) return <div className="text-zinc-400">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex gap-3 items-center">
        <h1 className="text-2xl font-bold">Equity Ticks</h1>
        <a href="/live" className="text-blue-400 text-sm hover:underline">
          ← back to live
        </a>
      </div>
      <div className="space-y-1">
        {entries.map((e) => (
          <div
            key={e.id}
            className="border border-zinc-800 rounded p-2 text-xs font-mono flex gap-4"
          >
            <span className="text-zinc-500 w-44">{e.ts}</span>
            <span className="text-green-400">
              eq: {e.input_state.equity?.toFixed(2) ?? "—"}
            </span>
            <span className="text-zinc-400">
              cash: {e.input_state.cash?.toFixed(2) ?? "—"}
            </span>
            <span className="text-zinc-500">
              peak: {e.input_state.peak?.toFixed(2) ?? "—"}
            </span>
            <span
              className={
                e.reconciliation_status === "ok"
                  ? "text-zinc-600"
                  : "text-yellow-400"
              }
            >
              {e.reconciliation_status}
            </span>
          </div>
        ))}
        {entries.length === 0 && (
          <div className="text-zinc-500">No snapshots yet.</div>
        )}
      </div>
    </div>
  );
}
