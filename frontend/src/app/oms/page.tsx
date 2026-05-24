"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

interface VenueStatus {
  name: string;
  configured: boolean;
  use_testnet: boolean;
}

interface OMSStatus {
  kill_switch_active: boolean;
  active_profile_id: string | null;
  active_profile_version: number | null;
  last_dispatch_ts: string | null;
  last_reconciliation_status: string | null;
  venues: VenueStatus[];
}

export default function OmsPage() {
  const [status, setStatus] = useState<OMSStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setStatus(await apiGet<OMSStatus>("/api/v1/oms/status"));
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

  async function killSwitch() {
    setBusy(true);
    try {
      await apiPost("/api/v1/oms/kill", { reason: "manual via UI" });
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
        <h1 className="text-2xl font-bold mb-2">OMS Status</h1>
        <div className="flex gap-4 items-center">
          <StatusBadge
            active={status.kill_switch_active}
            label={status.kill_switch_active ? "KILL SWITCH ACTIVE" : "running"}
          />
          <button
            onClick={killSwitch}
            disabled={busy || status.kill_switch_active}
            className="px-3 py-1 bg-red-900 text-red-100 rounded hover:bg-red-800 disabled:opacity-50"
          >
            {busy ? "..." : "Kill"}
          </button>
        </div>
      </div>

      <section>
        <h2 className="text-lg font-semibold mb-2">Active Profile</h2>
        <div className="text-sm font-mono text-zinc-300">
          {status.active_profile_id ?? "(none)"} · v{status.active_profile_version ?? "?"}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-2">Last Dispatch</h2>
        <div className="text-sm font-mono text-zinc-300">
          {status.last_dispatch_ts ?? "(none)"} → {status.last_reconciliation_status ?? "?"}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-2">Venues</h2>
        <div className="space-y-1">
          {status.venues.map((v) => (
            <div key={v.name} className="flex gap-3 items-center text-sm">
              <span className="font-mono w-24">{v.name}</span>
              <StatusBadge active={v.configured} label={v.configured ? "configured" : "missing"} />
              <StatusBadge active={!v.use_testnet} label={v.use_testnet ? "testnet" : "MAINNET"} />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
