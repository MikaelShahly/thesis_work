import { useEffect, useRef, useState } from "react";
import { AttachIcon, SendIcon, StopIcon } from "./icons.jsx";

// File extensions accepted by the geometry uploader. Mirrored on the
// backend (`GEOMETRY_EXTENSIONS` in src/config.py) — keep in sync.
const ACCEPTED_GEOMETRY = ".stl,.obj,.ply,.vtk,.nas,.ftr,.off,.x3d,.step,.stp,.iges,.igs";

// Build the message body sent to the agent from the typed text plus
// any attached geometry chips. Three shapes:
//   - text only            → text
//   - text + chip(s)       → "<text>\n\n[Geometry attached: a.stl, b.stl]"
//   - chip(s), no text     → "User uploaded geometry: a.stl, b.stl"
// Filenames refer to files inside `<project>/Geometry/` (the chip's
// `path` is relative to the project root). Listing names in the
// message keeps the system prompt token-cheap; the agent reads the
// actual files via Read/Bash from the path the prompt references.
function buildMessage(text, chips) {
  const trimmed = text.trim();
  if (chips.length === 0) return trimmed;
  const names = chips.map((c) => c.name).join(", ");
  if (trimmed) return `${trimmed}\n\n[Geometry attached: ${names}]`;
  return `User uploaded geometry: ${names}`;
}

// Interactive composer. Enter sends; Shift+Enter inserts a newline.
//
// `streaming` flips true while a turn is in flight. In that mode the
// send button morphs into a stop button (click → `onInterrupt`), but
// the textarea stays enabled so the user can type their next message
// ahead of time — they click Stop, the SSE wraps up, and the typed
// text is still in the box ready to send. Enter is a no-op while
// streaming so the user has to make the Stop choice explicitly.
//
// `disabled` is kept for the (rare) case where we want the composer
// fully inert even when no turn is running (none today, but mirrors
// AcceptPanel's shape).
//
// `onUploadGeometry(file)` (optional): async, returns a record with
// `{name, path, type, size}` on success. The composer drives the
// upload feedback (spinner + chip render) entirely; App owns the
// network call and the post-upload tree refresh.
export default function Composer({
  onSend,
  onInterrupt,
  onUploadGeometry,
  streaming = false,
  disabled = false,
  phaseLabel = "Simulation specification",
  placeholder = "Describe your simulation, or ask a follow-up…",
}) {
  const [text, setText] = useState("");
  const [chips, setChips] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const ref = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  // When a turn ends, put focus back in the composer.
  useEffect(() => {
    if (!disabled && !streaming) ref.current?.focus();
  }, [disabled, streaming]);

  // Auto-grow the textarea upward as the user types. CSS min/max-height
  // caps the range; past max-height the textarea scrolls internally
  // instead of pushing the chat further up.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  function submit() {
    if (disabled || streaming || uploading) return;
    const message = buildMessage(text, chips);
    if (!message) return;
    onSend?.(message);
    setText("");
    setChips([]);
    setUploadError(null);
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // While streaming, Enter is a no-op — the user must click Stop
      // explicitly. Pressing it during streaming silently does nothing
      // so the typed text isn't accidentally lost or sent prematurely.
      if (!streaming) submit();
    }
  }

  function handleAttachClick() {
    if (disabled || streaming || uploading || !onUploadGeometry) return;
    fileInputRef.current?.click();
  }

  async function handleFilePicked(e) {
    const input = e.target;
    const file = input.files?.[0];
    // Always reset the input so picking the same file twice still
    // fires onChange.
    input.value = "";
    if (!file || !onUploadGeometry) return;

    setUploading(true);
    setUploadError(null);
    try {
      const record = await onUploadGeometry(file);
      // Record shape from POST /geometry: { name, path, type, size, subfolder }.
      setChips((prev) => [...prev, record]);
    } catch (err) {
      console.error("geometry upload failed:", err);
      setUploadError(String(err.message || err));
    } finally {
      setUploading(false);
    }
  }

  function removeChip(path) {
    // Removes the chip from the composer state only. The uploaded
    // file stays on disk under <project>/Geometry/ — the user can
    // see it in the sidebar tree and can attach a different one
    // next time. (We avoid a "delete from disk" gesture here so
    // accidental chip-removal isn't destructive.)
    setChips((prev) => prev.filter((c) => c.path !== path));
  }

  const hasContent = text.trim().length > 0 || chips.length > 0;
  const canSend = hasContent && !disabled && !streaming && !uploading;
  const attachDisabled = disabled || streaming || uploading || !onUploadGeometry;

  return (
    <div className="composer-wrap">
      {(chips.length > 0 || uploadError) && (
        <div className="composer-chips">
          {chips.map((chip) => (
            <span key={chip.path} className="composer-chip" title={chip.path}>
              <AttachIcon size={11} />
              <span className="composer-chip-name">{chip.name}</span>
              <button
                type="button"
                className="composer-chip-remove"
                onClick={() => removeChip(chip.path)}
                aria-label={`Remove ${chip.name}`}
                title="Remove"
              >
                ×
              </button>
            </span>
          ))}
          {uploadError && (
            <span className="composer-chip is-error" role="alert">
              {uploadError}
              <button
                type="button"
                className="composer-chip-remove"
                onClick={() => setUploadError(null)}
                aria-label="Dismiss error"
              >
                ×
              </button>
            </span>
          )}
        </div>
      )}
      <div className={`composer ${disabled ? "is-disabled" : ""}`}>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_GEOMETRY}
          onChange={handleFilePicked}
          style={{ display: "none" }}
        />
        <button
          type="button"
          className={`composer-attach ${uploading ? "is-loading" : ""}`}
          onClick={handleAttachClick}
          disabled={attachDisabled}
          title={
            onUploadGeometry
              ? "Attach geometry (.stl, .obj, .step, …)"
              : "Geometry attach unavailable"
          }
          aria-label="Attach geometry"
        >
          <AttachIcon />
        </button>
        <textarea
          ref={ref}
          className="composer-input"
          placeholder={
            streaming
              ? "Type your next message — click Stop to interrupt the agent…"
              : placeholder
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          rows={1}
        />
        {streaming ? (
          <button
            type="button"
            className="composer-send composer-stop"
            onClick={onInterrupt}
            title="Stop the agent"
            aria-label="Stop the agent"
          >
            <StopIcon />
          </button>
        ) : (
          <button
            className="composer-send"
            disabled={!canSend}
            onClick={submit}
          >
            <SendIcon />
          </button>
        )}
      </div>
      <div className="composer-hint">
        <span>
          {streaming
            ? "Click Stop to interrupt · ⇧⏎ newline"
            : "⏎ send · ⇧⏎ newline"}
        </span>
        <span className="composer-phase">
          <span className="phase-dot" />
          {phaseLabel}
        </span>
      </div>
    </div>
  );
}

// Exposed so the sister test file can drive the message-building
// rules without rendering the component.
export { buildMessage };
