import { useCallback, useEffect, useRef, useState } from "react";

// useToastQueue — small queue manager for stacked transient notifications.
//
// At most `visibleCap` toasts are shown at once. Excess items wait in the
// queue and become visible (with their full `duration`) only once an
// earlier toast has expired and been removed. This means a 5th toast
// won't burn its 2.5s timer offscreen.
//
// `enqueue(payload)` pushes a new toast. `dismiss(id)` starts its exit
// animation and removes it after `exitDuration`. `reset()` clears
// everything (used on project switch).
export function useToastQueue({
  visibleCap = 4,
  duration = 2500,
  exitDuration = 250,
} = {}) {
  const [items, setItems] = useState([]); // { id, payload, isLeaving }
  const timersRef = useRef(new Map()); // id -> timeout for the 2.5s auto-dismiss

  const dismiss = useCallback(
    (id) => {
      setItems((prev) =>
        prev.map((n) => (n.id === id ? { ...n, isLeaving: true } : n)),
      );
      const t = timersRef.current.get(id);
      if (t) clearTimeout(t);
      timersRef.current.delete(id);
      setTimeout(() => {
        setItems((prev) => prev.filter((n) => n.id !== id));
      }, exitDuration);
    },
    [exitDuration],
  );

  const enqueue = useCallback((payload) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setItems((prev) => [...prev, { id, payload, isLeaving: false }]);
  }, []);

  const reset = useCallback(() => {
    for (const t of timersRef.current.values()) clearTimeout(t);
    timersRef.current.clear();
    setItems([]);
  }, []);

  // Start the 2.5s auto-dismiss timer when an item lands inside the
  // visible window. Items that are still queued (offscreen) get no
  // timer until they're promoted.
  useEffect(() => {
    const visible = items.slice(0, visibleCap);
    const visibleIds = new Set(visible.map((n) => n.id));
    visible.forEach((n) => {
      if (n.isLeaving) return;
      if (timersRef.current.has(n.id)) return;
      const t = setTimeout(() => dismiss(n.id), duration);
      timersRef.current.set(n.id, t);
    });
    // Drop timers tied to items that fell out of the visible window
    // (or were removed entirely).
    for (const [id, t] of timersRef.current) {
      if (!visibleIds.has(id)) {
        clearTimeout(t);
        timersRef.current.delete(id);
      }
    }
  }, [items, visibleCap, duration, dismiss]);

  // Cleanup on unmount.
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    };
  }, []);

  return {
    visible: items.slice(0, visibleCap),
    enqueue,
    dismiss,
    reset,
  };
}
