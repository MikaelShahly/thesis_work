// Persisted divider marking where the SDK auto-compacted the
// conversation context. Mirrors PhaseDivider's structure (line · pill ·
// line) so it reads as a sibling event in the chat stream. When the
// token counts are known, shows the reduction (e.g. "168k → 9.6k").

function formatTokens(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  if (n >= 1000) {
    const k = n / 1000;
    return `${k >= 100 ? Math.round(k) : k.toFixed(1)}k`;
  }
  return String(n);
}

export default function CompactionDivider({ preTokens, postTokens }) {
  const pre = formatTokens(preTokens);
  const post = formatTokens(postTokens);
  const showDelta = pre && post;

  return (
    <div className="phase-div compaction-div">
      <div className="phase-line" />
      <div className="phase-pill">
        <span className="phase-from">Context compacted</span>
        {showDelta && (
          <>
            <svg width="14" height="10" viewBox="0 0 14 10" fill="none">
              <path
                d="M1 5 Q 5 1, 7 5 T 13 5"
                stroke="var(--terracotta)"
                strokeWidth="1.4"
                fill="none"
                strokeLinecap="round"
              />
            </svg>
            <span className="phase-to">
              {pre} → {post} tokens
            </span>
          </>
        )}
      </div>
      <div className="phase-line" />
    </div>
  );
}
