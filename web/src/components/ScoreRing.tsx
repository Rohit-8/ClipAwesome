export function ScoreRing({ score, size = 52, stroke = 4.5, dim }: { score: number; size?: number; stroke?: number; dim?: boolean }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, score / 100));
  const color = dim ? "rgba(255,255,255,0.25)" : score >= 70 ? "#34d399" : score >= 45 ? "#7c66ff" : "#686b76";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} aria-label={`Score ${Math.round(score)} of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          style={{ transition: "stroke-dashoffset 600ms ease-out" }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="tabular font-semibold text-fg" style={{ fontSize: size * 0.3 }}>
          {Math.round(score)}
        </span>
      </div>
    </div>
  );
}
