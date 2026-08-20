// SVG components lifted verbatim from docs/AgenticCFD_Design (2).jsx.
// Keep these visually identical to the design reference.

export function BrandMark({ size = 22, color = "var(--terracotta)" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <path
        d="M3 18 C 8 18, 9 9, 14 9 C 19 9, 20 18, 25 18"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M5 22 C 10 22, 11 13, 16 13 C 21 13, 22 22, 27 22"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
        opacity="0.5"
      />
      <circle cx="14" cy="9" r="1.6" fill={color} />
    </svg>
  );
}

export function StreamlineLoader({ size = 20 }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        width: size * 1.4,
        height: size,
      }}
    >
      <svg width={size * 1.4} height={size} viewBox="0 0 28 20" fill="none">
        <defs>
          <linearGradient id="sl-fade" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--terracotta)" stopOpacity="0" />
            <stop offset="50%" stopColor="var(--terracotta)" stopOpacity="0.9" />
            <stop offset="100%" stopColor="var(--terracotta)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          d="M1 6 Q 8 2, 14 6 T 27 6"
          stroke="url(#sl-fade)"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
        >
          <animate attributeName="stroke-dashoffset" values="0;-40" dur="1.6s" repeatCount="indefinite" />
          <animate attributeName="stroke-dasharray" values="6 34" dur="0s" fill="freeze" />
        </path>
        <path
          d="M1 10 Q 8 14, 14 10 T 27 10"
          stroke="url(#sl-fade)"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
          opacity="0.7"
        >
          <animate attributeName="stroke-dashoffset" values="0;-40" dur="2.1s" repeatCount="indefinite" />
          <animate attributeName="stroke-dasharray" values="5 35" dur="0s" fill="freeze" />
        </path>
        <path
          d="M1 14 Q 8 10, 14 14 T 27 14"
          stroke="url(#sl-fade)"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
          opacity="0.5"
        >
          <animate attributeName="stroke-dashoffset" values="0;-40" dur="1.9s" repeatCount="indefinite" />
          <animate attributeName="stroke-dasharray" values="4 36" dur="0s" fill="freeze" />
        </path>
      </svg>
    </span>
  );
}

export function FolderIcon({ size = 14 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <path d="M1.5 3.5 h3.5 l1.2 1.2 h6.3 v6.3 a0.8 0.8 0 0 1 -0.8 0.8 h-10.2 a0.8 0.8 0 0 1 -0.8 -0.8 v-6.7 a0.8 0.8 0 0 1 0.8 -0.8 z" />
    </svg>
  );
}

// ─── Small UI glyphs ─────────────────────────────────────────────
export function PlusIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14">
      <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

// Chevron pointing right (used in the collapsed rail).
export function ChevronRightIcon({ size = 12 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
    >
      <path d="M4 2l4 5-4 5" />
    </svg>
  );
}

// Tree-row chevron — downward when expanded, rotates -90° (right-pointing)
// when collapsed. Matches docs/AgenticCFD_Design (5).jsx.
export function TreeChevronIcon({ expanded = false, size = 9 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      style={{
        transform: expanded ? "rotate(0deg)" : "rotate(-90deg)",
        transition: "transform 0.15s",
      }}
    >
      <path d="M3 5l4 4 4-4" />
    </svg>
  );
}

// Chevron pointing left (used in the expanded header collapse button).
export function ChevronLeftIcon({ size = 14 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
    >
      <path d="M10 2l-4 5 4 5" />
    </svg>
  );
}

export function SunIcon({ size = 13 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    >
      <circle cx="7" cy="7" r="3.5" />
      <path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.8 2.8l1 1M10.2 10.2l1 1M2.8 11.2l1-1M10.2 3.8l1-1" />
    </svg>
  );
}

export function MoonIcon({ size = 13 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    >
      <path d="M12 8.5A5.5 5.5 0 1 1 5.5 2c3 0 5.5 2 6.5 6.5z" />
    </svg>
  );
}

export function AttachIcon({ size = 16 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    >
      <path d="M11 5 L5.5 10.5 A2 2 0 0 0 8.5 13.5 L13 9 A3.5 3.5 0 0 0 8 4 L3.5 8.5" />
    </svg>
  );
}

export function SendIcon({ size = 14 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 7h10M8 3l4 4-4 4" />
    </svg>
  );
}

export function StopIcon({ size = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="currentColor">
      <rect x="2" y="2" width="8" height="8" rx="1.5" />
    </svg>
  );
}

// ParaView toolbar glyph: the brand's three slanted bars in its
// red/green/blue palette — instantly recognisable as ParaView. Filled
// with the official mark colours (not currentColor), so it keeps its
// identity regardless of the toolbar's accent/ochre theme.
export function ParaviewIcon({ size = 16 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
    >
      <polygon points="1.2,13.5 3.8,13.5 6.0,2.5 3.4,2.5" fill="#E0322B" />
      <polygon points="5.0,13.5 7.6,13.5 9.8,2.5 7.2,2.5" fill="#34A94C" />
      <polygon points="8.8,13.5 11.4,13.5 13.6,2.5 11.0,2.5" fill="#2566A8" />
    </svg>
  );
}

export function TrashIcon({ size = 13 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2.5 3.5h9M5 3.5V2.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1M3.5 3.5l.5 8a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1l.5-8M6 6v4M8 6v4" />
    </svg>
  );
}
