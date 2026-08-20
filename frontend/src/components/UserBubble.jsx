export default function UserBubble({ children }) {
  return (
    <div className="msg user">
      <div className="bubble user-bubble">{children}</div>
    </div>
  );
}
