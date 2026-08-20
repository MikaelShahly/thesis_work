import { useState } from "react";

// Replaces the Composer in the chat column when the agent requests
// permission to call a non-allowlisted tool. The agent is paused on
// the backend awaiting our decision; clicking Allow or Deny POSTs the
// decision to /api/projects/{pid}/permission/{tool_use_id}.
//
// Two modes (mirroring AcceptPanel's shape so the design language is
// consistent):
//
//   "pick"     — default. Shows the command preview, Deny/Allow, and
//                a "Deny with feedback →" link below the buttons.
//   "feedback" — user clicked the link; the preview is replaced with
//                a textarea + Cancel/Send. Send routes the user's text
//                through the deny-feedback endpoint, which resolves
//                the SDK permission Future with the typed message as
//                the deny reason — the agent receives it in place of
//                the canned DENY_MESSAGE and keeps running.
//
// Bash gets a dedicated rendering (the common case for this project).
// Other tools fall back to a generic JSON pretty-print.

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

function BashBody({ input, agentLabel }) {
  const command = typeof input?.command === "string" ? input.command : "";
  const description =
    typeof input?.description === "string" ? input.description : "";
  const title = agentLabel
    ? `[${agentLabel}] wants to run the following bash command`
    : "Allow the following bash command";
  return (
    <>
      <div className="perm-panel-title">{title}</div>
      <pre className="perm-panel-code">{command}</pre>
      {description ? (
        <div className="perm-panel-desc">{description}</div>
      ) : null}
    </>
  );
}

function GenericBody({ tool, input, agentLabel }) {
  let pretty;
  try {
    pretty = JSON.stringify(input ?? {}, null, 2);
  } catch {
    pretty = String(input);
  }
  const title = agentLabel
    ? `[${agentLabel}] wants to use tool: ${tool}`
    : `Allow tool: ${tool}`;
  return (
    <>
      <div className="perm-panel-title">{title}</div>
      <pre className="perm-panel-code">{pretty}</pre>
    </>
  );
}

export default function PermissionPanel({
  tool,
  input,
  agentLabel = null,
  pending = false,
  onAllow,
  onDeny,
  onDenyWithFeedback,
}) {
  const [mode, setMode] = useState("pick");
  const [draft, setDraft] = useState("");
  const isBash = tool === "Bash";

  if (mode === "feedback") {
    const canSend = draft.trim().length > 0 && !pending;
    return (
      <div className="composer-wrap">
        <div className="perm-panel">
          <div className="perm-panel-head">
            <div className="perm-panel-title">Reason for denying</div>
            <button
              type="button"
              className="perm-panel-close"
              onClick={() => {
                setDraft("");
                setMode("pick");
              }}
              title="Back"
              aria-label="Back"
            >
              <CloseIcon />
            </button>
          </div>
          <textarea
            className="perm-panel-textarea"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Tell the agent why — it will adjust its approach…"
            autoFocus
          />
          <div className="perm-panel-actions">
            <button
              className="sp-btn"
              onClick={() => {
                setDraft("");
                setMode("pick");
              }}
            >
              Cancel
            </button>
            <button
              className="sp-btn primary"
              disabled={!canSend}
              onClick={() => {
                if (!canSend) return;
                const text = draft.trim();
                setDraft("");
                setMode("pick");
                onDenyWithFeedback?.(text);
              }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="composer-wrap">
      <div className="perm-panel">
        {isBash ? (
          <BashBody input={input} agentLabel={agentLabel} />
        ) : (
          <GenericBody tool={tool} input={input} agentLabel={agentLabel} />
        )}
        <div className="perm-panel-actions">
          <button
            className="sp-btn"
            onClick={onDeny}
            disabled={pending}
          >
            Deny
          </button>
          <button
            className="sp-btn primary"
            onClick={onAllow}
            disabled={pending}
          >
            Allow
          </button>
        </div>
        {onDenyWithFeedback && (
          <div className="perm-panel-feedback-row">
            <button
              type="button"
              className="perm-panel-feedback-link"
              onClick={() => setMode("feedback")}
              disabled={pending}
            >
              Deny with feedback
              <ArrowIcon />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
