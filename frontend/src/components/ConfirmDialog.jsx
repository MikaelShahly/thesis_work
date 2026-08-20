import { useEffect, useRef } from "react";

// Centered modal dialog with Cancel + Confirm buttons. Click the
// backdrop or press Escape to cancel. Autofocuses Cancel (the safe
// default) so an accidental Enter doesn't confirm a destructive op.
export default function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null);

  useEffect(() => {
    cancelRef.current?.focus();
    function onKey(e) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="dialog-backdrop" onMouseDown={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="dialog-title">{title}</div>
        {message && <div className="dialog-sub">{message}</div>}
        <div className="dialog-actions">
          <button ref={cancelRef} className="dialog-btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            className={`dialog-btn ${danger ? "dialog-btn-danger" : ""}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
