import { BrandMark, StreamlineLoader } from "./icons.jsx";
import ExpandableEvent from "./ExpandableEvent.jsx";
import Markdown from "./Markdown.jsx";

// Agent-side chat row. The avatar cross-fades between the streamline
// loader (while the turn is still streaming) and the brand mark (once
// sealed by turn_complete). The cross-fade is CSS-driven via the
// `.is-streaming` class so the small in-flight glyph on the inline
// event row can land in the same beat — see styles.css "Loader handoff".
//
// `segments` is an ordered list of `{kind: text|thinking|tool, ...}`
// entries. Consecutive non-text segments are grouped into a single
// `.event-history` block so reasoning / tool rows visually cluster
// between prose paragraphs.
//
// Sub-agent activity carries an `agentLabel` on each segment. We
// prefix the label of thinking/tool rows with `[<label>]` and prepend
// an italic `[<label>]` line to text segments so the user can tell
// which agent produced what.
export default function AgentMessage({
  streaming = false,
  segments = [],
  interrupted = false,
}) {
  const groups = groupSegments(segments);

  return (
    <div className="msg agent">
      <div className={`agent-mark${streaming ? " is-streaming" : ""}`}>
        <span className="agent-mark-loader">
          <StreamlineLoader size={20} />
        </span>
        <span className="agent-mark-brand">
          <BrandMark size={20} />
        </span>
      </div>
      <div className="agent-body">
        {groups.map((group, gi) => {
          if (group.kind === "text") {
            const prefix = group.agentLabel ? `*[${group.agentLabel}]*\n\n` : "";
            return <Markdown key={gi} source={prefix + group.content} />;
          }
          return (
            <div key={gi} className="event-history">
              {group.items.map((seg, si) => (
                <ExpandableEvent
                  key={si}
                  kind={seg.kind}
                  status={seg.status}
                  label={labelFor(seg)}
                  desc={descFor(seg)}
                  content={seg.content}
                  input={seg.input}
                  output={seg.output}
                  isError={seg.isError}
                />
              ))}
            </div>
          );
        })}
        {interrupted && (
          <span className="agent-interrupted-chip">interrupted</span>
        )}
      </div>
    </div>
  );
}

// Walk the segment list, emitting either a "text" group (one text
// segment with its content + scope label) or an "events" group (one
// or more consecutive thinking / tool segments) so the renderer can
// wrap each event run in a single `.event-history` container.
function groupSegments(segments) {
  const out = [];
  let buffer = null;
  for (const seg of segments) {
    if (seg.kind === "text") {
      if (buffer) {
        out.push({ kind: "events", items: buffer });
        buffer = null;
      }
      out.push({
        kind: "text",
        content: seg.content ?? "",
        agentLabel: seg.agentLabel || null,
      });
    } else {
      if (!buffer) buffer = [];
      buffer.push(seg);
    }
  }
  if (buffer) out.push({ kind: "events", items: buffer });
  return out;
}

// Muted one-line summary shown after the tool name (see ExpandableEvent).
// Bash/Agent carry an authored `description`; the search tools surface
// their operative argument instead (query / url) — truthful and free, no
// tool-side change. Anything else renders bare (detail lives on expand).
function descFor(seg) {
  if (seg.kind !== "tool") return "";
  const input = seg.input;
  if (!input || typeof input !== "object") return "";
  const trim = (v) => (typeof v === "string" ? v.trim() : "");
  if (trim(input.description)) return trim(input.description);
  // seg.tool is the short name — the backend strips the mcp__<server>__
  // prefix (core.py::_short_tool_name) before it reaches the UI.
  const tool = seg.tool || "";
  if (tool === "WebSearch" || tool === "paper_search") return trim(input.query);
  if (tool === "web_fetch") return trim(input.url);
  return "";
}

function labelFor(seg) {
  const running = seg.status === "running";
  let base;
  if (seg.kind === "thinking") {
    base = running ? "Reasoning…" : "Reasoning";
  } else if (seg.kind === "tool") {
    const name = seg.tool || "tool";
    base = running ? `Using ${name}…` : `Using ${name}`;
  } else {
    base = "";
  }
  return seg.agentLabel ? `[${seg.agentLabel}] ${base}` : base;
}
