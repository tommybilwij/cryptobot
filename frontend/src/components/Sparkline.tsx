"use client";

interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
}

export function Sparkline({ values, width = 600, height = 80, className = "" }: SparklineProps) {
  if (values.length < 2) {
    return <div className={`text-zinc-500 text-sm ${className}`}>Not enough data</div>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const dx = width / (values.length - 1);
  const points = values
    .map((v, i) => `${(i * dx).toFixed(2)},${(height - ((v - min) / range) * height).toFixed(2)}`)
    .join(" ");

  const last = values[values.length - 1];
  const trend = last >= values[0] ? "stroke-green-400" : "stroke-red-400";

  return (
    <svg width={width} height={height} className={className}>
      <polyline points={points} fill="none" strokeWidth={2} className={trend} />
      <text x={width - 5} y={15} textAnchor="end" className="text-xs fill-zinc-400 font-mono">
        {last.toFixed(2)}
      </text>
    </svg>
  );
}
