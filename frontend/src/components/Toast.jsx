import { FolderIcon, ParaviewIcon } from "./icons.jsx";

// Subfolder color ramp — kept in sync with Sidebar's SUBFOLDER_COLOR.
const SUBFOLDER_COLOR = {
  Specification: "#B8553C",
  Cases: "var(--ochre)",
  Reports: "var(--sage)",
  Geometry: "var(--indigo)",
};

// Toast renderer with two payload variants:
//
//   { kind: 'file', name, subfolder, path, type }
//      — file-write toast emitted from agent activity.
//   { kind: 'message', title, body?, icon?: 'paraview' }
//      — generic info / error toast (e.g. ParaView 409 from /launch).
//
// Older payloads without `kind` are treated as 'file' so prior call
// sites keep working unchanged. `onOpen` fires on click; for message
// toasts the click just dismisses (the parent passes a no-op or the
// dismiss callback).
export default function Toast({ notification, onOpen }) {
  const { payload, isLeaving } = notification;
  const kind = payload.kind ?? "file";

  if (kind === "message") {
    const Icon = payload.icon === "paraview" ? ParaviewIcon : FolderIcon;
    return (
      <button
        className={`toast ${isLeaving ? "is-leaving" : ""}`}
        onClick={onOpen}
        role="status"
      >
        <span className="toast-icon" style={{ color: "var(--ink-3)" }}>
          <Icon size={14} />
        </span>
        <span className="toast-text">
          <span className="toast-name">{payload.title}</span>
          {payload.body && <span className="toast-sub">{payload.body}</span>}
        </span>
      </button>
    );
  }

  return (
    <button
      className={`toast ${isLeaving ? "is-leaving" : ""}`}
      onClick={onOpen}
      role="status"
    >
      <span
        className="toast-icon"
        style={{ color: SUBFOLDER_COLOR[payload.subfolder] ?? "var(--ink-3)" }}
      >
        <FolderIcon size={14} />
      </span>
      <span className="toast-text">
        <span className="toast-name">{payload.name}</span>
        <span className="toast-sub">added to {payload.subfolder}</span>
      </span>
    </button>
  );
}
