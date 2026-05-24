"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiGet, apiPost } from "@/lib/api";

interface Profile {
  id: string;
  name: string;
  version: number;
  is_active: boolean;
  config: Record<string, unknown>;
}

export default function EditProfilePage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [profile, setProfile] = useState<Profile | null>(null);
  const [configText, setConfigText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiGet<Profile>(`/api/v1/strategy-profiles/${id}`)
      .then((p) => {
        setProfile(p);
        setConfigText(JSON.stringify(p.config, null, 2));
      })
      .catch((e) => setErr((e as Error).message));
  }, [id]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const parsed = JSON.parse(configText);
      await apiPost(`/api/v1/strategy-profiles/${id}/update-config`, { config: parsed });
      router.push("/profiles");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!profile) return <div className="text-zinc-400">Loading…</div>;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Edit: {profile.name}</h1>
      <p className="text-sm text-zinc-500">
        v{profile.version} {profile.is_active && "· active"}
      </p>
      <textarea
        value={configText}
        onChange={(e) => setConfigText(e.target.value)}
        className="w-full h-96 p-3 bg-zinc-900 border border-zinc-700 rounded font-mono text-sm"
        spellCheck={false}
      />
      <div className="flex gap-2">
        <button
          onClick={save}
          disabled={saving}
          className="px-4 py-2 bg-blue-900 text-blue-100 rounded hover:bg-blue-800 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <button
          onClick={() => router.push("/profiles")}
          className="px-4 py-2 bg-zinc-800 text-zinc-300 rounded hover:bg-zinc-700"
        >
          Cancel
        </button>
      </div>
      {err && <div className="text-red-400 text-sm">{err}</div>}
    </div>
  );
}
