"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

interface Profile {
  id: string;
  name: string;
  version: number;
  is_active: boolean;
  config: Record<string, unknown>;
}

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  async function refresh() {
    try {
      setProfiles(await apiGet<Profile[]>("/api/v1/strategy-profiles"));
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
  if (!profiles) return <div className="text-zinc-400">Loading…</div>;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Profiles</h1>
      <div className="space-y-2">
        {profiles.map((p) => (
          <div key={p.id} className="border border-zinc-800 rounded p-3">
            <div className="flex gap-3 items-center">
              <button
                onClick={() => setExpanded(expanded === p.id ? null : p.id)}
                className="text-blue-400 hover:underline font-mono text-sm"
              >
                {p.name}
              </button>
              <span className="text-xs text-zinc-500">v{p.version}</span>
              <StatusBadge active={p.is_active} label={p.is_active ? "active" : "inactive"} />
            </div>
            {expanded === p.id && (
              <pre className="mt-2 text-xs text-zinc-400 bg-zinc-900 p-2 rounded overflow-x-auto">
                {JSON.stringify(p.config, null, 2)}
              </pre>
            )}
          </div>
        ))}
        {profiles.length === 0 && <div className="text-zinc-500">No profiles yet.</div>}
      </div>
    </div>
  );
}
