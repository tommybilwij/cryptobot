"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

interface VenueHealth {
  name: string;
  configured: boolean;
  use_testnet: boolean;
  reachable: boolean;
  balance_quote: number | null;
  error: string | null;
}

interface HealthResponse {
  venues: VenueHealth[];
}

export default function ExchangesPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      setHealth(await apiGet<HealthResponse>("/api/v1/exchanges/health"));
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
  if (!health) return <div className="text-zinc-400">Loading…</div>;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Exchange Health</h1>
      <div className="space-y-1">
        {health.venues.map((v) => (
          <div key={v.name} className="border border-zinc-800 rounded p-3 flex gap-4 items-center">
            <span className="font-mono w-28">{v.name}</span>
            <StatusBadge active={v.configured} label={v.configured ? "configured" : "missing keys"} />
            <StatusBadge active={!v.use_testnet} label={v.use_testnet ? "testnet" : "MAINNET"} />
            <StatusBadge active={v.reachable} label={v.reachable ? "reachable" : "unreachable"} />
            <span className="font-mono text-sm">
              {v.balance_quote != null ? `$${v.balance_quote.toFixed(2)}` : "—"}
            </span>
            {v.error && <span className="text-red-400 text-xs">{v.error}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
