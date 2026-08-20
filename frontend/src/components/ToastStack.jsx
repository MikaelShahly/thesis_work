import Toast from "./Toast.jsx";

// Vertical stack of new-file toasts pinned to the top-left of the chat
// column. Renders nothing when there are no visible toasts (so the
// stack doesn't reserve layout space).
export default function ToastStack({ notifications, onOpen }) {
  if (!notifications.length) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {notifications.map((n) => (
        <Toast key={n.id} notification={n} onOpen={() => onOpen(n)} />
      ))}
    </div>
  );
}
