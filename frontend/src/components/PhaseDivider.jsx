// User-facing phase labels. Keys match `project.phase` / history
// entry `from`/`to` values from the backend.
const PHASE_LABEL = {
  simulation_spec: "Simulation specification",
  case_builder: "Case building",
  mesh: "Meshing",
  improver: "Running",
  post_process: "Post-processing",
};

export default function PhaseDivider({ from, to }) {
  return (
    <div className="phase-div">
      <div className="phase-line" />
      <div className="phase-pill">
        <span className="phase-from">{PHASE_LABEL[from] ?? from}</span>
        <svg width="14" height="10" viewBox="0 0 14 10" fill="none">
          <path
            d="M1 5 Q 5 1, 7 5 T 13 5"
            stroke="var(--terracotta)"
            strokeWidth="1.4"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
        <span className="phase-to">{PHASE_LABEL[to] ?? to}</span>
      </div>
      <div className="phase-line" />
    </div>
  );
}
