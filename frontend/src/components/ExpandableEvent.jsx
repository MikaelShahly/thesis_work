import { useState } from "react";
import { StreamlineLoader } from "./icons.jsx";

// Inline event row that can be clicked to reveal a payload — replaces
// the plain italic event line for any reasoning or tool call that
// carries content worth showing.
//
//   kind="thinking" → expand reveals reasoning prose.
//   kind="tool"     → expand reveals Input (the tool's input dict) and
//                     Output (the tool's normalized result text) in two
//                     bounded boxes.
//
// While `status === "running"` the row shows a small streamline pulse
// in place of the chevron, dovetailing with the agent-message avatar's
// loader fade-out (handled in CSS). The row is still expandable while
// running as long as it has a payload — thinking blocks stream their
// content in via `thinking_delta` so the user can click to watch
// reasoning populate live.
export default function ExpandableEvent({
  kind,
  status,
  label,
  desc,
  content,
  input,
  output,
  isError,
}) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = status === "running";
  const hasPayload =
    kind === "thinking"
      ? !!(content && content.trim())
      : !!(input || (output && output.toString().length > 0));
  const canExpand = hasPayload;

  function handleClick() {
    if (canExpand) setExpanded((v) => !v);
  }

  return (
    <div
      className={
        `xevent${expanded ? " is-open" : ""}${isRunning ? " is-running" : ""}`
      }
    >
      <button
        type="button"
        className="xevent-row"
        onClick={handleClick}
        disabled={!canExpand}
      >
        <span className="xevent-marker">
          {isRunning ? (
            <StreamlineLoader size={14} />
          ) : (
            <svg
              className={`xevent-chev${expanded ? " is-open" : ""}`}
              width="9"
              height="9"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            >
              <path d="M5 3l4 4-4 4" />
            </svg>
          )}
        </span>
        <span className="xevent-label">{label}</span>
        {desc && <span className="xevent-desc">{desc}</span>}
      </button>

      {expanded && (
        <div className="xevent-body">
          {kind === "thinking" && content && (
            <div className="xevent-prose">
              {content.split("\n\n").map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </div>
          )}

          {kind === "tool" && input != null && (
            <>
              <div className="xevent-section-label">Input</div>
              <div className="xevent-box">
                <pre className="xevent-pre">{formatToolInput(input)}</pre>
              </div>
            </>
          )}

          {kind === "tool" && output != null && output !== "" && (
            <>
              <div className="xevent-section-label">
                Output{isError ? " (error)" : ""}
              </div>
              <div className={`xevent-box${isError ? " is-error" : ""}`}>
                <pre className="xevent-pre">{output}</pre>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Pretty-print the tool input. Strings pass through (some tools take
// a single string). Objects/arrays JSON-pretty-print so the user sees
// keys/values one per line.
function formatToolInput(input) {
  if (typeof input === "string") return input;
  try {
    return JSON.stringify(input, null, 2);
  } catch {
    return String(input);
  }
}
