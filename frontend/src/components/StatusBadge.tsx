export function StatusBadge({ active, label }: { active: boolean; label: string }) {
  return (
    <span
      className={`inline-block px-2 py-1 rounded text-xs font-mono ${
        active ? "bg-green-900 text-green-300" : "bg-zinc-800 text-zinc-400"
      }`}
    >
      {label}
    </span>
  );
}
