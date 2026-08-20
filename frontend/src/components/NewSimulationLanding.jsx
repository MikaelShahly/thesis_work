import { useEffect, useMemo, useRef, useState } from "react";
import { BrandMark, SendIcon } from "./icons.jsx";
import { slugify } from "../lib/slugify.js";

const LEVELS = [
  { id: "beginner", label: "Beginner", desc: "I'm new to CFD — guide me through this" },
  { id: "intermediate", label: "Intermediate", desc: "I have working CFD knowledge" },
  { id: "expert", label: "Expert", desc: "I know exactly what I need" },
];

// Landing screen rendered in the chat-column slot when no project is
// selected. Collects name + expertise level, POSTs to /api/projects,
// then hands the new project id back to the app (via onCreate).
//
// `projects` is the sidebar's current list — used to block duplicate
// names (same slug) before they hit the backend, so the user sees a
// clean inline error instead of a 409.
export default function NewSimulationLanding({ onCreate, projects = [] }) {
  const [name, setName] = useState("");
  const [level, setLevel] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const nameRef = useRef(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Precompute existing folder slugs for the dup check. Prefer the
  // backend's stored `folder_name` when available; fall back to
  // slugifying the project name.
  const takenSlugs = useMemo(
    () => new Set(projects.map((p) => p.folder_name || slugify(p.name))),
    [projects],
  );

  const trimmed = name.trim();
  const candidateSlug = trimmed ? slugify(trimmed) : "";
  const isDuplicate = !!candidateSlug && takenSlugs.has(candidateSlug);
  const canStart =
    trimmed.length > 0 && level !== null && !submitting && !isDuplicate;

  async function start() {
    if (!canStart) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate?.({ name: trimmed, expertise_level: level });
    } catch (err) {
      setError(err.message ?? String(err));
      setSubmitting(false);
    }
  }

  function onNameKeyDown(e) {
    if (e.key === "Enter" && canStart) {
      e.preventDefault();
      start();
    }
  }

  return (
    <div className="chat-scroll">
      <div className="chat-inner new-sim-inner">
        <div className="new-sim-mark"><BrandMark size={36} /></div>
        <h2 className="new-sim-title">Start a new simulation</h2>
        <p className="new-sim-sub">
          Name your project and choose your experience level. This helps the agent calibrate its questions.
        </p>

        <div className="new-sim-field">
          <label className="new-sim-label">Project name</label>
          <input
            ref={nameRef}
            className="new-sim-input"
            type="text"
            placeholder="e.g. NACA 0012 airfoil study"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={onNameKeyDown}
            disabled={submitting}
          />
          {isDuplicate && (
            <div className="new-sim-inline-warning">
              A project with that name already exists — pick something different.
            </div>
          )}
        </div>

        <div className="new-sim-field">
          <label className="new-sim-label">Experience level</label>
          <div className="new-sim-levels">
            {LEVELS.map((l) => (
              <button
                key={l.id}
                className={`new-sim-level ${level === l.id ? "is-active" : ""}`}
                onClick={() => setLevel(l.id)}
                disabled={submitting}
              >
                <span className="new-sim-level-name">{l.label}</span>
                <span className="new-sim-level-desc">{l.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <button className="new-sim-start" disabled={!canStart} onClick={start}>
          <SendIcon />
          {submitting ? "Starting…" : "Start simulation"}
        </button>
        {error && <div className="new-sim-error">Couldn't create project: {error}</div>}
      </div>
    </div>
  );
}
