import { useState } from "react";

// Replaces the Composer in the chat column while the user is
// reviewing a draft specification. Three modes (§9.4):
//
//   "pick"     — the default after `specification_presented`.
//                Shows Yes / No options + an "Ask a question" exit.
//   "feedback" — user clicked "No, provide feedback"; shows a textarea
//                + Cancel / Send buttons.
//   "accepted" — transient; shows a "Specification approved" badge
//                while the POST /approve-spec call is in flight.
//
// The panel is purely presentational — all state transitions live in
// useAgentStream. `mode` and the action callbacks come in as props.

function CheckIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none">
      <path
        d="M2 7l3 3 7-7"
        stroke="var(--sage)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon({ size = 12 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
    >
      <path d="M3 3l6 6M9 3l-6 6" />
    </svg>
  );
}

function ArrowIcon({ size = 12 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    >
      <path d="M2 6h8M7 3l3 3-3 3" />
    </svg>
  );
}

// Default copy targets the simulation_spec phase (its first consumer).
// case_builder passes overrides via the `copy` prop.
const DEFAULT_COPY = {
  pickTitle: "Accept this simulation specification?",
  feedbackTitle: "Feedback on specification",
  feedbackPlaceholder: "What would you change? The agent will revise.",
  acceptedLabel: "Specification approved",
  yesSub: "begin case building",
  noSub: "revise and re-present",
};

export default function AcceptPanel({
  mode,
  streaming = false,
  onAskQuestion,
  onOpenFeedback,
  onCancelFeedback,
  onSubmitFeedback,
  onApprove,
  copy,
}) {
  const [draft, setDraft] = useState("");
  const c = { ...DEFAULT_COPY, ...(copy ?? {}) };

  if (mode === "accepted") {
    return (
      <div className="composer-wrap">
        <div className="accept-panel">
          <div className="accept accept-done">
            <CheckIcon />
            {c.acceptedLabel}
          </div>
        </div>
      </div>
    );
  }

  if (mode === "feedback") {
    const canSend = draft.trim().length > 0;
    return (
      <div className="composer-wrap">
        <div className="accept-panel">
          <div className="accept-panel-head">
            <div className="accept-panel-title">{c.feedbackTitle}</div>
            <button
              className="accept-panel-close"
              onClick={() => {
                setDraft("");
                onCancelFeedback?.();
              }}
              title="Back"
            >
              <CloseIcon />
            </button>
          </div>
          <textarea
            className="accept-panel-textarea"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={c.feedbackPlaceholder}
            autoFocus
          />
          <div className="accept-panel-actions">
            <button
              className="sp-btn"
              onClick={() => {
                setDraft("");
                onCancelFeedback?.();
              }}
            >
              Cancel
            </button>
            <button
              className="sp-btn primary"
              disabled={!canSend || streaming}
              onClick={() => {
                if (!canSend || streaming) return;
                const text = draft.trim();
                setDraft("");
                onSubmitFeedback?.(text);
              }}
            >
              Send feedback
            </button>
          </div>
        </div>
      </div>
    );
  }

  // "pick" (default). Yes/No are disabled while the agent is still
  // streaming — approving (or sending feedback) mid-turn would abort
  // the stream and leave the last agent message visually stuck.
  // "Ask a question →" stays live: it just switches the UI.
  return (
    <div className="composer-wrap">
      <div className="accept-panel">
        <div className="accept-panel-head">
          <div className="accept-panel-title">{c.pickTitle}</div>
          <button
            className="accept-panel-exit"
            onClick={onAskQuestion}
            title="Exit review — ask a question instead"
          >
            Ask a question
            <ArrowIcon />
          </button>
        </div>
        <div className="accept-panel-opts">
          <button
            className="accept-opt accept-yes"
            onClick={onApprove}
            disabled={streaming}
          >
            <span className="opt-mark">●</span>
            <span>
              <span className="opt-title">Yes, proceed</span>
              <span className="opt-sub">{c.yesSub}</span>
            </span>
          </button>
          <button
            className="accept-opt accept-no"
            onClick={onOpenFeedback}
            disabled={streaming}
          >
            <span className="opt-mark">○</span>
            <span>
              <span className="opt-title">No, provide feedback</span>
              <span className="opt-sub">{c.noSub}</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
