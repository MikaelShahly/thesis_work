import { useState } from "react";
import { ParaviewIcon } from "./icons.jsx";

// Tiny toolbar button — one state, one click handler. The plan
// explicitly rejects status polling and a state machine; the only
// transient state is "request in flight" so we can dim the icon
// while we wait. Everything else (success → ParaView window
// appears; conflict → toast) is owned by the caller.
//
// `onLaunch` is async; it should resolve once the POST has come
// back (regardless of whether it was a launch, a 409, or an error).
// Toasting on conflict is the caller's job — we just clear the
// spinner so the user can try again.
export default function ParaviewLaunchButton({ onLaunch, disabled = false }) {
  const [loading, setLoading] = useState(false);

  async function handleClick() {
    if (loading || disabled) return;
    setLoading(true);
    try {
      await onLaunch?.();
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      type="button"
      className={`pv-toolbar-btn ${loading ? "is-loading" : ""}`}
      onClick={handleClick}
      disabled={disabled || loading}
      title="Open ParaView (share state with the agent)."
      aria-label="Open ParaView"
    >
      <ParaviewIcon size={16} />
    </button>
  );
}
