"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

interface AuditEntry {
  id: string;
  ts: string;
  strategy_name: string;
  profile_version: number;
  profile_hash: string;
  decision_type: string;
  orders: unknown[];
  fills: unknown[];
  reconciliation_status: string;
  reason: string | null;
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [strategyFilter, setStrategyFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (strategyFilter) params.set("strategy_name", strategyFilter);
      if (typeFilter) params.set("decision_type", typeFilter);
      setEntries(await apiGet<AuditEntry[]>(`/api/v1/decision-audit/recent?${params}`));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [strategyFilter, typeFilter]);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!entries) return <div className="text-zinc-400">Loading…</div>;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Decision Audit</h1>
      <div className="flex gap-3 text-sm">
        <input
          type="text"
          placeholder="Filter strategy"
          value={strategyFilter}
          onChange={(e) => setStrategyFilter(e.target.value)}
          className="px-2 py-1 bg-zinc-900 border border-zinc-700 rounded font-mono"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-2 py-1 bg-zinc-900 border border-zinc-700 rounded font-mono"
        >
          <option value="">all types</option>
          <option value="order">order</option>
          <option value="snapshot">snapshot</option>
        </select>
      </div>
      <div className="space-y-1">
        {entries.map((e) => (
          <div key={e.id} className="border border-zinc-800 rounded p-2 text-xs font-mono">
            <div className="flex gap-3 items-center">
              <span className="text-zinc-500">{e.ts}</span>
              <span className="text-blue-400">{e.strategy_name}</span>
              <span
                className={
                  e.reconciliation_status === "ok"
                    ? "text-green-400"
                    : e.reconciliation_status.startsWith("halt")
                      ? "text-red-400"
                      : "text-yellow-400"
                }
              >
                {e.reconciliation_status}
              </span>
              <span className="text-zinc-500">v{e.profile_version}</span>
              <span className="text-zinc-600">{e.decision_type}</span>
              <span className="text-zinc-500">
                {e.orders.length}o/{e.fills.length}f
              </span>
            </div>
            {e.reason && <div className="mt-1 text-red-400">{e.reason}</div>}
          </div>
        ))}
        {entries.length === 0 && <div className="text-zinc-500">No entries.</div>}
      </div>
    </div>
  );
}
