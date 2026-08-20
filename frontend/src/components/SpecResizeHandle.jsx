import { useRef } from "react";

// Vertical drag handle for a resizable column. Width is owned by the
// parent (App) and persisted to localStorage; this component is pure UI.
//
// `side` sets which edge the resized panel lives on:
//   - "right" (default): the panel is to the RIGHT of the handle (spec
//     panel), so dragging LEFT widens it.
//   - "left": the panel is to the LEFT of the handle (sidebar), so
//     dragging RIGHT widens it.
//
// Mouse listeners are attached to `document`, not the handle element,
// so the drag keeps working even if the cursor leaves the 8px handle
// strip during a fast drag.
export default function SpecResizeHandle({ width, setWidth, min = 260, max = 600, side = "right" }) {
  const startRef = useRef({ x: 0, w: 0 });

  function onMouseDown(e) {
    e.preventDefault();
    startRef.current = { x: e.clientX, w: width };

    function onMove(ev) {
      const delta =
        side === "left"
          ? ev.clientX - startRef.current.x
          : startRef.current.x - ev.clientX;
      const next = Math.max(min, Math.min(max, startRef.current.w + delta));
      setWidth(next);
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div className="resize-handle" onMouseDown={onMouseDown}>
      <div className="resize-grip" />
    </div>
  );
}
