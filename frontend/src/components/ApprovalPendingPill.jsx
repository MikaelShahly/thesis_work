// Slim two-part bar that sits above the composer in case_builder
// "approval_pending" / "approval_pending_streaming" states (plan §4.6).
// Left: non-clickable status. Right: Approve button — disabled while
// the agent is mid-turn so a one-click approve can't race a streaming
// response.
export default function ApprovalPendingPill({ onApprove, streaming = false }) {
  return (
    <div className="approval-pill-wrap">
      <div className="approval-pill">
        <span className="approval-pill-status">
          <span className="approval-pill-dot" />
          Approval pending
        </span>
        <button
          className="approval-pill-approve"
          onClick={onApprove}
          disabled={streaming}
          title={streaming ? "Waiting for the agent to finish this turn" : undefined}
        >
          Approve
        </button>
      </div>
    </div>
  );
}
