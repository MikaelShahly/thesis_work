import Markdown from "./Markdown.jsx";

function CheckIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none">
      <path
        d="M2 7l3 3 7-7"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// Right-pane component for Phase 1 review. Shows the latest
// `present_specification` draft. An approve footer is rendered only
// when `onApprove` is passed — the parent passes it once the user has
// dismissed the AcceptPanel (clicked "Ask a question →"), so approval
// is still reachable without the agent re-calling the tool.
export default function SpecPanel({ title, markdown, onApprove, streaming = false }) {
  return (
    <aside className="spec-panel">
      <div className="spec-panel-head">
        <div>
          <div className="spec-panel-kicker">Current specification</div>
          <div className="spec-panel-title">{title}</div>
        </div>
      </div>
      <div className="spec-panel-body">
        <Markdown source={markdown ?? ""} />
      </div>
      {onApprove && (
        <div className="spec-panel-foot">
          <button
            className="spec-approve-btn"
            onClick={onApprove}
            disabled={streaming}
            title={streaming ? "Waiting for the agent to finish this turn" : undefined}
          >
            <CheckIcon />
            Approve specification
          </button>
        </div>
      )}
    </aside>
  );
}
