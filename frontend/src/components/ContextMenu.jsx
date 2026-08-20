import { useEffect, useRef } from "react";

// A minimal floating menu positioned at screen coordinates. Closes on
// outside mousedown or Escape. Re-positions automatically when the
// parent rebuilds it at new coordinates (e.g. right-clicking a
// different row).
export default function ContextMenu({ x, y, onClose, children }) {
  const ref = useRef(null);

  useEffect(() => {
    function onDocMouseDown(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    }
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="context-menu"
      style={{ left: x, top: y }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {children}
    </div>
  );
}
