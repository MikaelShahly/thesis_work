import { useState, useEffect } from "react";

// ═══════════════════════════════════════════════════════════════
// AgenticCFD — Design System Preview
// Warm minimalism · paper + ink + terracotta
// ═══════════════════════════════════════════════════════════════

// ─── Phase colors ───
// Maps both project-level and subfolder-level phase keys to a single ramp.
const PHASE_COLOR = {
  Spec: "var(--terracotta)",
  Case: "var(--ochre)",
  Mesh: "var(--ochre)",
  Meshing: "var(--ochre)",
  Run: "var(--ochre)",
  Running: "var(--ochre)",
  Post: "var(--sage)",
  Done: "var(--ink-3)",
};

// ─── Brand Mark ───
function BrandMark({ size = 22, color = "var(--terracotta)" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <path d="M3 18 C 8 18, 9 9, 14 9 C 19 9, 20 18, 25 18" stroke={color} strokeWidth="1.8" strokeLinecap="round" fill="none"/>
      <path d="M5 22 C 10 22, 11 13, 16 13 C 21 13, 22 22, 27 22" stroke={color} strokeWidth="1.8" strokeLinecap="round" fill="none" opacity="0.5"/>
      <circle cx="14" cy="9" r="1.6" fill={color}/>
    </svg>
  );
}

// ─── Loaders ───
function StreamlineLoader({ size = 20 }) {
  return (
    <span style={{ display:"inline-flex", alignItems:"center", width: size*1.4, height: size }}>
      <svg width={size*1.4} height={size} viewBox="0 0 28 20" fill="none">
        <defs>
          <linearGradient id="sl-fade" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--terracotta)" stopOpacity="0"/>
            <stop offset="50%" stopColor="var(--terracotta)" stopOpacity="0.9"/>
            <stop offset="100%" stopColor="var(--terracotta)" stopOpacity="0"/>
          </linearGradient>
        </defs>
        <path d="M1 6 Q 8 2, 14 6 T 27 6" stroke="url(#sl-fade)" strokeWidth="1.4" fill="none" strokeLinecap="round">
          <animate attributeName="stroke-dashoffset" values="0;-40" dur="1.6s" repeatCount="indefinite"/>
          <animate attributeName="stroke-dasharray" values="6 34" dur="0s" fill="freeze"/>
        </path>
        <path d="M1 10 Q 8 14, 14 10 T 27 10" stroke="url(#sl-fade)" strokeWidth="1.4" fill="none" strokeLinecap="round" opacity="0.7">
          <animate attributeName="stroke-dashoffset" values="0;-40" dur="2.1s" repeatCount="indefinite"/>
          <animate attributeName="stroke-dasharray" values="5 35" dur="0s" fill="freeze"/>
        </path>
        <path d="M1 14 Q 8 10, 14 14 T 27 14" stroke="url(#sl-fade)" strokeWidth="1.4" fill="none" strokeLinecap="round" opacity="0.5">
          <animate attributeName="stroke-dashoffset" values="0;-40" dur="1.9s" repeatCount="indefinite"/>
          <animate attributeName="stroke-dasharray" values="4 36" dur="0s" fill="freeze"/>
        </path>
      </svg>
    </span>
  );
}



// ─── Sidebar ───
function FolderIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" strokeLinecap="round">
      <path d="M1.5 3.5 h3.5 l1.2 1.2 h6.3 v6.3 a0.8 0.8 0 0 1 -0.8 0.8 h-10.2 a0.8 0.8 0 0 1 -0.8 -0.8 v-6.7 a0.8 0.8 0 0 1 0.8 -0.8 z"/>
    </svg>
  );
}

function Sidebar({ active = "wing-airfoil", initialCollapsed = false, darkMode = false, onToggleDark, accent, onAccent, accents = {}, onNewSim, onSelectProject, selectedFileId, onSelectFile, expandedSubfolders, onToggleSubfolder }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const projects = [
    {
      id: "wing-airfoil",
      name: "NACA 0012 airfoil",
      phase: "Case",
      updated: "just now",
      artifacts: [
        {
          id: "spec",
          name: "Specification",
          phase: "Spec",
          files: [
            { id: "specification.md", name: "specification.md", type: "md", content: SPEC_MD },
          ],
        },
        {
          id: "case",
          name: "Case",
          phase: "Case",
          inProgress: true,
          files: [
            { id: "controlDict", name: "controlDict", type: "dict", content: CONTROL_DICT },
            { id: "fvSchemes", name: "fvSchemes", type: "dict", content: FV_SCHEMES },
            { id: "fvSolution", name: "fvSolution", type: "dict", content: FV_SOLUTION, isNew: true },
          ],
        },
      ],
    },
    { id: "pipe-flow", name: "Turbulent pipe flow", phase: "Meshing", updated: "2h",
      artifacts: [
        {
          id: "spec",
          name: "Specification",
          phase: "Spec",
          files: [{ id: "specification.md", name: "specification.md", type: "md", content: PIPE_SPEC_MD }],
        },
        {
          id: "mesh",
          name: "Mesh",
          phase: "Mesh",
          inProgress: true,
          files: [{ id: "blockMeshDict", name: "blockMeshDict", type: "dict", content: BLOCK_MESH_DICT, isNew: true }],
        },
      ],
    },
    { id: "heat-exch", name: "Heat exchanger", phase: "Running", updated: "yesterday" },
    { id: "vortex", name: "Karman vortex shedding", phase: "Post", updated: "3d" },
    { id: "cavity", name: "Lid-driven cavity", phase: "Done", updated: "1w" },
  ];
  // phaseColor moved to module-level PHASE_COLOR (used by SubfolderRow too).

  if (collapsed) {
    return (
      <aside className="sb is-collapsed">
        <button className="sb-rail" onClick={() => setCollapsed(false)} title="Open sidebar">
          <div className="sb-rail-brand"><BrandMark size={22}/></div>
          <div className="sb-rail-icons">
            <div className="sb-rail-btn" title="New simulation">
              <svg width="14" height="14" viewBox="0 0 14 14"><path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
            </div>
            <div className="sb-rail-btn" title="Projects"><FolderIcon/></div>
          </div>
          <div className="sb-rail-chev">
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M4 2l4 5-4 5"/></svg>
          </div>
        </button>
      </aside>
    );
  }

  return (
    <aside className="sb">
      <div className="sb-head">
        <div className="sb-brand"><BrandMark size={22}/><div><div className="sb-brand-name">AgenticCFD</div><div className="sb-brand-sub">local · v0.3</div></div></div>
        <button className="sb-toggle" onClick={() => setCollapsed(true)} title="Collapse">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M10 2l-4 5 4 5"/></svg>
        </button>
      </div>
      <button className="sb-new" onClick={onNewSim}>
        <svg width="14" height="14" viewBox="0 0 14 14"><path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
        New simulation
      </button>
      <div className="sb-section scroll-hidden">
        <div className="sb-section-label">Projects</div>
        {projects.map(p => (
          <div key={p.id}>
            <div
              className={`sb-proj ${p.id === active ? "is-active" : ""}`}
              onClick={() => onSelectProject && onSelectProject(p.id)}
              role="button"
              tabIndex={0}
            >
              <div className="sb-proj-icon" style={{ color: PHASE_COLOR[p.phase] }}><FolderIcon/></div>
              <div className="sb-proj-body">
                <div className="sb-proj-name">{p.name}</div>
                <div className="sb-proj-meta"><span>{p.phase}</span><span className="dot-sep">·</span><span>{p.updated}</span></div>
              </div>
            </div>
            {p.id === active && p.artifacts && p.artifacts.length > 0 && (
              <div className="sb-tree">
                {p.artifacts.map(sub => (
                  <SubfolderRow
                    key={sub.id}
                    subfolder={sub}
                    expanded={expandedSubfolders ? !!expandedSubfolders[sub.id] : undefined}
                    onToggle={onToggleSubfolder ? () => onToggleSubfolder(sub.id) : undefined}
                    selectedFileId={selectedFileId}
                    onSelectFile={onSelectFile}
                  />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="sb-foot">
        {/* Theme */}
        <div className="sb-setting">
          <div className="sb-setting-label">Theme</div>
          <button className="sb-theme-toggle" onClick={onToggleDark}>
            {darkMode ? (
              <><svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><circle cx="7" cy="7" r="3.5"/><path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.8 2.8l1 1M10.2 10.2l1 1M2.8 11.2l1-1M10.2 3.8l1-1"/></svg><span>Light</span></>
            ) : (
              <><svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><path d="M12 8.5A5.5 5.5 0 1 1 5.5 2c3 0 5.5 2 6.5 6.5z"/></svg><span>Dark</span></>
            )}
          </button>
        </div>
        {/* Accent */}
        <div className="sb-setting">
          <div className="sb-setting-label">Accent</div>
          <div className="sb-accent-row">
            {Object.entries(accents).map(([k, v]) => (
              <button key={k} className={`sb-accent-dot ${accent === k ? "is-active" : ""}`} style={{background: v.primary}} onClick={() => onAccent && onAccent(k)} title={k}/>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

// ─── Chat primitives ───
function UserBubble({ children }) {
  return <div className="msg user"><div className="bubble user-bubble">{children}</div></div>;
}

// streaming = true  → avatar shows the streamline loader (initial wait state)
// streaming = false → avatar shows the static brand mark
// The two glyphs are stacked and cross-fade so the transition is smooth — the
// outgoing loader flows into the small streamline on the in-flight event row.
function AgentMessage({ children, streaming = false }) {
  return (
    <div className="msg agent">
      <div className={`agent-mark ${streaming ? "is-streaming" : ""}`}>
        <span className="agent-mark-loader"><StreamlineLoader size={20}/></span>
        <span className="agent-mark-brand"><BrandMark size={20}/></span>
      </div>
      <div className="agent-body">{children}</div>
    </div>
  );
}

// Simplified event line — just italic text in lighter color
function EventLine({ text }) {
  return <div className="event-line">{text}</div>;
}

// ─── Expandable event ──────────────────────────────────────
// Replacement for EventLine when the event has a payload to reveal.
// kind = "thinking" → renders a single bounded prose box on expand.
// kind = "tool"     → renders Input + Output sections, both bounded mono boxes.
// status = "running" shows the streamline pulse glyph; "done" shows the chevron.
// onOpenWorkspace gets the workspace-link payload (if any) when user clicks it.
function ExpandableEvent({
  kind = "thinking",
  label,
  status = "done",
  reasoning,
  input,
  output,
  workspaceLink,
  defaultExpanded = false,
  onOpenWorkspace,
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const isRunning = status === "running";
  const canExpand = !isRunning && (reasoning || input || output);
  const handleClick = () => { if (canExpand) setExpanded(v => !v); };
  return (
    <div className={`xevent ${expanded ? "is-open" : ""} ${isRunning ? "is-running" : ""}`}>
      <button className="xevent-row" onClick={handleClick} disabled={!canExpand}>
        <span className="xevent-marker">
          {isRunning
            ? <StreamlineLoader size={14}/>
            : <svg className={`xevent-chev ${expanded ? "is-open" : ""}`} width="9" height="9" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M5 3l4 4-4 4"/></svg>}
        </span>
        <span className="xevent-label">{label}</span>
      </button>
      {expanded && (
        <div className="xevent-body">
          {kind === "thinking" && reasoning && (
            <div className="xevent-prose">
              {reasoning.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
            </div>
          )}
          {kind === "tool" && input && (
            <>
              <div className="xevent-section-label">Input</div>
              <div className="xevent-box xevent-box-mono"><DictView content={input}/></div>
            </>
          )}
          {kind === "tool" && output && (
            <>
              <div className="xevent-section-label">Output</div>
              <div className="xevent-box xevent-box-mono"><DictView content={output}/></div>
            </>
          )}
          {workspaceLink && (
            <button className="xevent-link" onClick={() => onOpenWorkspace && onOpenWorkspace(workspaceLink)}>
              <FolderIcon size={11}/>
              Open {workspaceLink.label} in workspace
            </button>
          )}
        </div>
      )}
    </div>
  );
}


function Composer({ disabled = false, placeholder = "Describe your simulation, or ask a follow-up…" }) {
  return (
    <div className="composer-wrap">
      <div className={`composer ${disabled ? "is-disabled" : ""}`}>
        <button className="composer-attach" title="Attach geometry (STL)">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><path d="M11 5 L5.5 10.5 A2 2 0 0 0 8.5 13.5 L13 9 A3.5 3.5 0 0 0 8 4 L3.5 8.5"/></svg>
        </button>
        <div className="composer-input" contentEditable suppressContentEditableWarning style={{color: disabled ? "var(--ink-4)" : "var(--ink-3)"}}>{placeholder}</div>
        <button className="composer-send" disabled={disabled}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M2 7h10M8 3l4 4-4 4"/></svg>
        </button>
      </div>
      <div className="composer-hint">
        <span>⏎ send  ·  ⇧⏎ newline</span>
        <span className="composer-phase"><span className="phase-dot"/>Simulation specification</span>
      </div>
    </div>
  );
}

function PhaseDivider({ from = "Simulation specification", to = "Case building" }) {
  return (
    <div className="phase-div">
      <div className="phase-line"/>
      <div className="phase-pill">
        <span className="phase-from">{from}</span>
        <svg width="14" height="10" viewBox="0 0 14 10" fill="none"><path d="M1 5 Q 5 1, 7 5 T 13 5" stroke="var(--terracotta)" strokeWidth="1.4" fill="none" strokeLinecap="round"/></svg>
        <span className="phase-to">{to}</span>
      </div>
      <div className="phase-line"/>
    </div>
  );
}

// ─── Markdown renderer ───
function parseInline(s) {
  const parts = []; const re = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0, m;
  while ((m = re.exec(s)) !== null) {
    if (m.index > last) parts.push(s.slice(last, m.index));
    if (m[1]) parts.push(<strong key={m.index}>{m[1]}</strong>);
    else if (m[2]) parts.push(<code key={m.index} className="md-inline-code">{m[2]}</code>);
    last = m.index + m[0].length;
  }
  if (last < s.length) parts.push(s.slice(last));
  return parts;
}

function Markdown({ source }) {
  const lines = source.trim().split("\n");
  const blocks = []; let list = null;
  const flushList = () => { if (list) { blocks.push(list); list = null; } };
  lines.forEach((ln, i) => {
    if (ln.startsWith("# ")) { flushList(); blocks.push(<h1 key={i} className="md-h1">{parseInline(ln.slice(2))}</h1>); }
    else if (ln.startsWith("## ")) { flushList(); blocks.push(<h2 key={i} className="md-h2">{parseInline(ln.slice(3))}</h2>); }
    else if (ln.startsWith("- ")) {
      const item = <li key={i} className="md-li">{parseInline(ln.slice(2))}</li>;
      if (!list) list = <ul key={`l${i}`} className="md-ul">{[item]}</ul>;
      else list = { ...list, props: { ...list.props, children: [...list.props.children, item] } };
    }
    else if (ln.startsWith("  - ")) {
      const item = <li key={i} className="md-li md-li-nested">{parseInline(ln.slice(4))}</li>;
      if (!list) list = <ul key={`l${i}`} className="md-ul">{[item]}</ul>;
      else list = { ...list, props: { ...list.props, children: [...list.props.children, item] } };
    }
    else if (ln.trim() === "") { flushList(); }
    else { flushList(); blocks.push(<p key={i} className="md-p">{parseInline(ln)}</p>); }
  });
  flushList();
  return <div className="md">{blocks}</div>;
}

const SPEC_MD = `# Simulation specification

External aerodynamics of a NACA 0012 airfoil at a moderate angle of attack.

## Case setup

- **Solver** — \`simpleFoam\` (steady, incompressible RANS)
- **Turbulence model** — k–ω SST
- **Working fluid** — air at 1 atm, 288.15 K (ν = 1.46 × 10⁻⁵ m²/s)
- **Domain** — C-grid, 20c upstream, 30c downstream, 20c cross-stream
- **Boundary conditions**
  - inlet: uniform velocity 15 m/s, turbulence intensity 0.5%
  - outlet: zero gradient pressure
  - airfoil: no-slip wall with wall functions
  - sides: symmetry

## Mesh requirements

- **Near-wall resolution** — y⁺ ≈ 1 for the first cell, geometric expansion ratio ≤ 1.15
- **Leading edge** — minimum 40 cells around the nose radius to capture the stagnation point and suction peak
- **Trailing edge** — refined wake region extending 3c downstream, cell aspect ratio ≤ 5
- **Total cell count** — target 120k–180k cells (2D extruded, 1 cell in z)
- **Quality checks** — max non-orthogonality < 65°, max skewness < 3.0

## Numerical schemes

- **Gradient** — Gauss linear with cell-limited correction
- **Divergence** — bounded Gauss linearUpwind for velocity, bounded Gauss upwind for turbulence quantities
- **Laplacian** — Gauss linear corrected
- **Interpolation** — linear
- **Relaxation factors** — U: 0.7, p: 0.3, k: 0.7, omega: 0.7

## Convergence criteria

- All residuals below 1 × 10⁻⁵
- Force coefficients (Cl, Cd) variation < 0.1% over last 200 iterations
- Monitor Cl and Cd every iteration

## Success criteria

Primary outcome: **lift and drag coefficients** at α = 4°, 8°, 12°,
within 5% of published XFOIL data. Secondary: identify stall onset and
confirm attached flow at α = 4°.

## Post-processing

- Pressure coefficient (Cp) distribution at each angle of attack
- Skin friction coefficient along the airfoil surface
- Velocity magnitude contours in the near-field
- Streamlines at α = 12° to check for separation
`;

// ─── Sample OpenFOAM dictionary content ───
const PIPE_SPEC_MD = `# Simulation specification

Fully developed turbulent flow through a smooth circular pipe at Re = 10⁵.

## Case setup

- **Solver** — \`pimpleFoam\` (transient, incompressible)
- **Turbulence model** — k–ω SST
- **Working fluid** — water at 20 °C (ν = 1.0 × 10⁻⁶ m²/s)
- **Geometry** — pipe of length 30 D, diameter D = 0.05 m
- **Boundary conditions**
  - inlet: cyclic with mean U = 2.0 m/s
  - outlet: cyclic
  - wall: no-slip, wall functions

## Mesh requirements

- y⁺ ≈ 1 at the wall
- 200 cells along the length, 40 in the radial direction
- O-grid topology to avoid singularities at the centerline

## Success criteria

Match the law of the wall (u⁺ vs y⁺) within 5 % of DNS data.
`;

const BLOCK_MESH_DICT = `FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}

scale   0.001;

vertices
(
    (   0   0    0)
    (  50   0    0)
    (  50  50    0)
    (   0  50    0)
    (   0   0 1500)
    (  50   0 1500)
    (  50  50 1500)
    (   0  50 1500)
);

blocks
(
    hex (0 1 2 3 4 5 6 7) (40 40 200) simpleGrading (1 1 1)
);

boundary
(
    wall
    {
        type wall;
        faces ( (0 3 2 1) (4 5 6 7) );
    }
    inlet
    {
        type cyclic;
        neighbourPatch outlet;
        faces ( (0 4 7 3) );
    }
    outlet
    {
        type cyclic;
        neighbourPatch inlet;
        faces ( (1 2 6 5) );
    }
);
`;

const CONTROL_DICT = `FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}

application     simpleFoam;

startFrom       startTime;
startTime       0;

stopAt          endTime;
endTime         2000;

deltaT          1;

writeControl    timeStep;
writeInterval   200;
purgeWrite      0;

writeFormat     ascii;
writePrecision  6;
timeFormat      general;
runTimeModifiable true;

functions
{
    forceCoeffs
    {
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         (airfoil);
        rho             rhoInf;
        rhoInf          1.225;
        liftDir         (0 1 0);
        dragDir         (1 0 0);
        CofR            (0.25 0 0);
        magUInf         15;
        lRef            1.0;
        Aref            1.0;
    }
}
`;

const FV_SCHEMES = `FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}

ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
}

divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}
`;

const FV_SOLUTION = `FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}

solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-7;
        relTol          0.01;
        smoother        GaussSeidel;
    }

    "(U|k|omega)"
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        tolerance       1e-8;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 1;
    consistent      yes;

    residualControl
    {
        p               1e-5;
        U               1e-5;
        "(k|omega)"     1e-5;
    }
}

relaxationFactors
{
    fields  { p  0.3; }
    equations
    {
        U           0.7;
        k           0.7;
        omega       0.7;
    }
}
`;

// ─── Tree primitives ───
function ChevronIcon({ expanded = true }) {
  return (
    <svg
      width="9" height="9" viewBox="0 0 14 14" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"
      style={{ transform: expanded ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" }}
    >
      <path d="M3 5l4 4 4-4"/>
    </svg>
  );
}

// Static streamline glyph echoing StreamlineLoader — used to mark an in-progress phase.
function StreamlinePulse({ color = "var(--terracotta)" }) {
  return (
    <svg width="14" height="6" viewBox="0 0 28 12" fill="none" style={{ opacity: 0.7 }}>
      <path d="M1 6 Q 8 2, 14 6 T 27 6" stroke={color} strokeWidth="1.4" fill="none" strokeLinecap="round">
        <animate attributeName="stroke-dashoffset" values="0;-40" dur="1.6s" repeatCount="indefinite"/>
        <animate attributeName="stroke-dasharray" values="6 34" dur="0s" fill="freeze"/>
      </path>
    </svg>
  );
}

function SubfolderRow({ subfolder, expanded: expandedProp, onToggle, selectedFileId, onSelectFile }) {
  // Hybrid controlled/uncontrolled. If parent passes `expanded`, it owns the state
  // (used by ViewWorkspace so toggle state survives sidebar collapse and resets
  // cleanly on project switch). Otherwise fall back to internal state for views
  // that haven't wired up expand-tracking. Default is collapsed in both cases.
  const [internalExpanded, setInternalExpanded] = useState(false);
  const isControlled = expandedProp !== undefined;
  const expanded = isControlled ? expandedProp : internalExpanded;
  const handleToggle = () => {
    if (isControlled) onToggle && onToggle();
    else setInternalExpanded(v => !v);
  };
  const color = PHASE_COLOR[subfolder.phase] || "var(--ink-3)";
  return (
    <div className="sb-sub">
      <button className="sb-sub-row" onClick={handleToggle}>
        <span className="sb-chev"><ChevronIcon expanded={expanded}/></span>
        <span className="sb-sub-icon" style={{ color }}><FolderIcon size={12}/></span>
        <span className="sb-sub-name">{subfolder.name}</span>
        {subfolder.inProgress && <span className="sb-sub-pulse"><StreamlinePulse color={color}/></span>}
      </button>
      {expanded && (
        <div className="sb-files">
          {subfolder.files.map(f => (
            <FileRow
              key={f.id}
              file={f}
              isActive={selectedFileId === f.id}
              onClick={() => onSelectFile && onSelectFile({ ...f, subfolderName: subfolder.name })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FileRow({ file, isActive, onClick }) {
  const isMono = file.type !== "md";
  return (
    <button
      className={`sb-file ${isActive ? "is-active" : ""} ${isMono ? "is-mono" : ""}`}
      onClick={onClick}
    >
      <span className="sb-file-name">{file.name}</span>
      {file.isNew && !isActive && <span className="sb-file-new" title="New since last viewed"/>}
    </button>
  );
}

// ─── Dict view (OpenFOAM dictionaries, logs, raw config) ───
function DictView({ content }) {
  const lines = content.split("\n");
  return (
    <div className="dict-view">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        const isComment = trimmed.startsWith("//") || trimmed.startsWith("/*") || trimmed.startsWith("*");
        const isBrace = trimmed === "{" || trimmed === "}";
        const cls = isComment ? "is-comment" : isBrace ? "is-brace" : "";
        return (
          <div key={i} className={`dict-line ${cls}`}>{line || "\u00A0"}</div>
        );
      })}
    </div>
  );
}

// ─── New-file toast notification ───
// Rendered in the top-left gutter of the chat column. Appears when the agent
// writes a new file; clicking opens that file in the right panel and expands
// its subfolder in the sidebar tree.
function Toast({ notification, onOpen }) {
  const { file, subfolderName, phase, isLeaving } = notification;
  return (
    <button
      className={`toast ${isLeaving ? "is-leaving" : ""}`}
      onClick={onOpen}
      role="status"
    >
      <span className="toast-icon" style={{ color: PHASE_COLOR[phase] || "var(--ink-3)" }}>
        <FolderIcon size={14}/>
      </span>
      <span className="toast-text">
        <span className="toast-name">{file.name}</span>
        <span className="toast-sub">added to {subfolderName}</span>
      </span>
    </button>
  );
}

function ToastStack({ notifications, onOpen }) {
  if (!notifications.length) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {notifications.map(n => (
        <Toast key={n.id} notification={n} onOpen={() => onOpen(n)}/>
      ))}
    </div>
  );
}

// ─── Spec components ───
function AcceptControl() {
  const [mode, setMode] = useState("closed");
  const [draft, setDraft] = useState("");

  if (mode === "accepted") {
    return (
      <div className="accept accept-done">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7l3 3 7-7" stroke="var(--sage)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
        Specification approved · moving to case building
      </div>
    );
  }

  if (mode === "feedback") {
    return (
      <div className="accept accept-feedback">
        <div className="accept-label">Your feedback</div>
        <textarea className="accept-textarea" rows={3} value={draft} onChange={e => setDraft(e.target.value)} placeholder="What would you change? The agent will revise." autoFocus/>
        <div className="accept-actions">
          <button className="btn-ghost" onClick={() => { setMode("closed"); setDraft(""); }}>Cancel</button>
          <button className="btn-primary" disabled={!draft.trim()} onClick={() => setMode("accepted")}>Send feedback</button>
        </div>
      </div>
    );
  }

  return (
    <div className="accept accept-pick">
      <div className="accept-q">Accept this simulation specification?</div>
      <div className="accept-opts">
        <button className="accept-opt accept-yes" onClick={() => setMode("accepted")}>
          <span className="opt-mark">●</span>
          <span><span className="opt-title">Yes</span><span className="opt-sub">proceed to case building</span></span>
        </button>
        <button className="accept-opt accept-no" onClick={() => setMode("feedback")}>
          <span className="opt-mark">○</span>
          <span><span className="opt-title">No, provide feedback</span><span className="opt-sub">revise and re-present</span></span>
        </button>
      </div>
      <div className="accept-hint">Or just ask a question — the agent will answer and re-present when ready.</div>
    </div>
  );
}

function SpecPanel({ project = "NACA 0012 airfoil", subfolder, file }) {
  // Empty state — nothing selected.
  if (!file) {
    return (
      <aside className="spec-panel">
        <div className="spec-panel-empty">
          <BrandMark size={28}/>
          <div className="spec-panel-empty-title">No file selected</div>
          <div className="spec-panel-empty-sub">Pick a file from the project tree on the left to preview it here.</div>
        </div>
      </aside>
    );
  }
  // Default behaviour preserved: if called without a file, used to show SPEC_MD.
  // The `file` prop now drives both header breadcrumb and body renderer.
  const kicker = subfolder ? `${project} · ${subfolder}` : project;
  return (
    <aside className="spec-panel">
      <div className="spec-panel-head">
        <div>
          <div className="spec-panel-kicker">{kicker}</div>
          <div className="spec-panel-title">{file.name}</div>
        </div>
      </div>
      <div className="spec-panel-body">
        {file.type === "md"
          ? <Markdown source={file.content}/>
          : <DictView content={file.content}/>}
      </div>
    </aside>
  );
}

// Note: ViewSpecSplit was updated to pass the spec file explicitly to <SpecPanel/>.
// If you need the old default-spec behavior again, just call SpecPanel with the file prop set.

function AcceptPanel() {
  const [mode, setMode] = useState("pick");
  const [draft, setDraft] = useState("");
  if (mode === "accepted") {
    return <div className="accept-panel"><div className="accept accept-done"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7l3 3 7-7" stroke="var(--sage)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>Specification approved</div></div>;
  }
  if (mode === "feedback") {
    return (
      <div className="accept-panel">
        <div className="accept-panel-head">
          <div className="accept-panel-title">Feedback on specification</div>
          <button className="accept-panel-close" onClick={() => setMode("pick")} title="Back">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M3 3l6 6M9 3l-6 6"/></svg>
          </button>
        </div>
        <textarea className="accept-panel-textarea" rows={3} value={draft} onChange={e => setDraft(e.target.value)} placeholder="What would you change? The agent will revise." autoFocus/>
        <div className="accept-panel-actions">
          <button className="sp-btn" onClick={() => setMode("pick")}>Cancel</button>
          <button className="sp-btn primary" disabled={!draft.trim()} onClick={() => setMode("accepted")}>Send feedback</button>
        </div>
      </div>
    );
  }
  return (
    <div className="accept-panel">
      <div className="accept-panel-head">
        <div className="accept-panel-title">Accept this simulation specification?</div>
        <button className="accept-panel-exit" title="Exit review — ask a question instead">
          Ask a question
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><path d="M2 6h8M7 3l3 3-3 3"/></svg>
        </button>
      </div>
      <div className="accept-panel-opts">
        <button className="accept-opt accept-yes" onClick={() => setMode("accepted")}>
          <span className="opt-mark">●</span>
          <span><span className="opt-title">Yes, proceed</span><span className="opt-sub">begin case building</span></span>
        </button>
        <button className="accept-opt accept-no" onClick={() => setMode("feedback")}>
          <span className="opt-mark">○</span>
          <span><span className="opt-title">No, provide feedback</span><span className="opt-sub">revise and re-present</span></span>
        </button>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// VIEWS
// ═══════════════════════════════════════════════════════════

function ViewChat({ sidebarProps = {} }) {
  return (
    <div className="app" style={{height:"100%"}}>
      <Sidebar active="wing-airfoil" {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div><div className="chat-title">NACA 0012 airfoil</div><div className="chat-title-sub">Started 14:18 · intermediate</div></div>
          <div className="chat-top-right"><span className="chat-phase"><span className="phase-dot"/>Simulation specification</span></div>
        </div>
        <div className="chat-scroll" style={{overflowY:"auto"}}>
          <div className="chat-inner">
            <UserBubble>I want to simulate flow over a NACA 0012 airfoil at a few angles of attack, around 15 m/s. Mainly interested in lift and drag curves.</UserBubble>

            {/* Completed agent message — brand mark shown */}
            <AgentMessage>
              <p className="md-p" style={{fontSize:14}}>Nice — that's a classic external-aerodynamics case. A few quick things to pin down before I draft the spec.</p>
              <ul className="md-ul">
                <li className="md-li">Do you want a 2D simulation (airfoil section) or 3D (finite wing)?</li>
                <li className="md-li">Which α range should I sweep — just pre-stall, or into stall?</li>
                <li className="md-li">Any preference for solver — steady RANS (<code className="md-inline-code">simpleFoam</code>) or unsteady?</li>
              </ul>
            </AgentMessage>

            <UserBubble>2D for now. α = 4°, 8°, 12°. Steady is fine if stall isn't a problem.</UserBubble>

            {/* Completed message with event history — shows what happened during processing */}
            <AgentMessage>
              <div className="event-history">
                <EventLine text="Reasoning…"/>
                <EventLine text="Using web_search…"/>
                <EventLine text="Using read_docs…"/>
                <EventLine text="Using compute_reynolds…"/>
              </div>
              <p className="md-p" style={{fontSize:14}}>At 15 m/s with chord ≈ 1 m, Reynolds is ~1.0 × 10⁶ — firmly turbulent. k–ω SST is the standard choice and resolves the leading-edge pressure gradient well. I'll propose a C-grid domain with 20c upstream and 30c downstream — enough to avoid blockage.</p>
            </AgentMessage>

            {/* Currently streaming — loader shown instead of brand mark */}
            <AgentMessage streaming={true}>
              <div className="event-history">
                <EventLine text="Reasoning…"/>
                <EventLine text="Using web_search…"/>
              </div>
              <EventLine text="Using present_specification…"/>
            </AgentMessage>
          </div>
        </div>
        <Composer/>
      </div>
    </div>
  );
}

function ViewSpecSplit({ sidebarProps = {} }) {
  const [specWidth, setSpecWidth] = useState(380);
  const dragging = React.useRef(false);

  const onMouseDown = (e) => {
    e.preventDefault();
    dragging.current = true;
    const startX = e.clientX;
    const startW = specWidth;
    const onMouseMove = (e) => {
      if (!dragging.current) return;
      const delta = startX - e.clientX;
      setSpecWidth(Math.max(260, Math.min(600, startW + delta)));
    };
    const onMouseUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div className="app" style={{height:"100%", gridTemplateColumns: `auto 1fr 0px ${specWidth}px`}}>
      <Sidebar initialCollapsed={true} {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div><div className="chat-title">NACA 0012 airfoil</div><div className="chat-title-sub">Review mode · specification on the right</div></div>
          <span className="chat-phase"><span className="phase-dot"/>Simulation specification · review</span>
        </div>
        <div className="chat-scroll" style={{overflowY:"auto"}}>
          <div className="chat-inner">
            <AgentMessage>
              <div className="event-history">
                <EventLine text="Using web_search…"/>
                <EventLine text="Using compute_reynolds…"/>
              </div>
              <p className="md-p" style={{fontSize:14}}>I've drafted the specification. When you're ready, accept below — or ask a question to leave review mode and the spec will stay visible.</p>
            </AgentMessage>
          </div>
        </div>
        <div className="composer-wrap"><AcceptPanel/></div>
      </div>
      {/* Resize handle */}
      <div className="resize-handle" onMouseDown={onMouseDown}>
        <div className="resize-grip"/>
      </div>
      <SpecPanel
        project="NACA 0012 airfoil"
        subfolder="Specification"
        file={{ name: "specification.md", type: "md", content: SPEC_MD }}
      />
    </div>
  );
}

function ViewPhase({ sidebarProps = {} }) {
  return (
    <div className="app" style={{height:"100%"}}>
      <Sidebar {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div><div className="chat-title">NACA 0012 airfoil</div><div className="chat-title-sub">Transitioned to case building · 14:47</div></div>
          <span className="chat-phase" style={{background:"var(--ochre-tint)", color:"var(--ochre)"}}><span className="phase-dot" style={{background:"var(--ochre)"}}/>Case building</span>
        </div>
        <div className="chat-scroll" style={{overflowY:"auto"}}>
          <div className="chat-inner">
            <AgentMessage>
              <div className="accept accept-done">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7l3 3 7-7" stroke="var(--sage)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                Specification approved
              </div>
            </AgentMessage>
            <PhaseDivider from="Simulation specification" to="Case building"/>
            <AgentMessage>
              <p className="md-p" style={{fontSize:14}}>Starting on the OpenFOAM case. I'll set up the directory tree, write the dictionaries, and configure boundary conditions from the spec. Tell me to pause if anything looks off.</p>
              <div className="event-history">
                <EventLine text="Using validate_geometry…"/>
              </div>
            </AgentMessage>
            {/* Currently working */}
            <AgentMessage streaming={true}>
              <EventLine text="Using generate_case_files…"/>
            </AgentMessage>
          </div>
        </div>
        <Composer/>
      </div>
    </div>
  );
}



function ViewWorkspace({ sidebarProps = {} }) {
  const [specWidth, setSpecWidth] = useState(440);
  const [activeProject, setActiveProject] = useState("wing-airfoil");
  const [expandedSubfolders, setExpandedSubfolders] = useState({});
  const [selectedFile, setSelectedFile] = useState({
    id: "specification.md",
    name: "specification.md",
    type: "md",
    content: SPEC_MD,
    subfolderName: "Specification",
  });
  // New-file toast queue. Each item carries the file data, its destination
  // subfolder, and a `isLeaving` flag we set just before removing it from DOM
  // so the exit animation can play.
  const [notifications, setNotifications] = useState([]);
  const dragging = React.useRef(false);

  const dismissNotification = (id) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, isLeaving: true } : n));
    setTimeout(() => {
      setNotifications(prev => prev.filter(n => n.id !== id));
    }, 250);
  };

  const showNotification = (payload) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setNotifications(prev => [...prev, { ...payload, id, isLeaving: false }]);
    setTimeout(() => dismissNotification(id), 2500);
  };

  // Clicking a toast: open the file in the right panel, expand its subfolder
  // in the tree, and dismiss the toast immediately.
  const handleOpenNotification = (n) => {
    setSelectedFile({ ...n.file, subfolderName: n.subfolderName });
    setExpandedSubfolders(prev => ({ ...prev, [n.subfolderId]: true }));
    dismissNotification(n.id);
  };

  // Demo trigger — simulates the agent writing fvSolution. In a real app this
  // would be dispatched by whatever tool call wrote the file.
  const triggerDemoNotification = () => {
    showNotification({
      file: { id: "fvSolution", name: "fvSolution", type: "dict", content: FV_SOLUTION },
      subfolderId: "case",
      subfolderName: "Case",
      phase: "Case",
    });
  };

  // Auto-fire once on mount so the design is visible without needing a click.
  useEffect(() => {
    const t = setTimeout(triggerDemoNotification, 1100);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelectProject = (id) => {
    if (id === activeProject) return;
    setActiveProject(id);
    setExpandedSubfolders({});
    setSelectedFile(null);
  };

  const handleToggleSubfolder = (subId) => {
    setExpandedSubfolders(prev => ({ ...prev, [subId]: !prev[subId] }));
  };

  const onMouseDown = (e) => {
    e.preventDefault();
    dragging.current = true;
    const startX = e.clientX;
    const startW = specWidth;
    const onMouseMove = (e) => {
      if (!dragging.current) return;
      const delta = startX - e.clientX;
      setSpecWidth(Math.max(280, Math.min(620, startW + delta)));
    };
    const onMouseUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const projectTitle = activeProject === "wing-airfoil" ? "NACA 0012 airfoil"
    : activeProject === "pipe-flow" ? "Turbulent pipe flow"
    : activeProject === "heat-exch" ? "Heat exchanger"
    : activeProject === "vortex" ? "Karman vortex shedding"
    : activeProject === "cavity" ? "Lid-driven cavity"
    : "Project";

  return (
    <div className="app" style={{ height: "100%", gridTemplateColumns: `auto 1fr 0px ${specWidth}px` }}>
      <Sidebar
        {...sidebarProps}
        active={activeProject}
        onSelectProject={handleSelectProject}
        expandedSubfolders={expandedSubfolders}
        onToggleSubfolder={handleToggleSubfolder}
        selectedFileId={selectedFile?.id}
        onSelectFile={setSelectedFile}
      />
      <div className="chat-col">
        <div className="chat-top">
          <div>
            <div className="chat-title">{projectTitle}</div>
            <div className="chat-title-sub">Workspace · browse generated artifacts</div>
          </div>
          <div className="chat-top-right">
            <button className="demo-trigger" onClick={triggerDemoNotification} title="Simulate the agent writing a new file">
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M6 2v8M2 6h8"/></svg>
              Simulate write
            </button>
            <span className="chat-phase" style={{ background: "var(--ochre-tint)", color: "var(--ochre)" }}>
              <span className="phase-dot" style={{ background: "var(--ochre)" }}/>Case building
            </span>
          </div>
        </div>
        <ToastStack notifications={notifications} onOpen={handleOpenNotification}/>
        <div className="chat-scroll" style={{ overflowY: "auto" }}>
          <div className="chat-inner">
            <AgentMessage>
              <div className="accept accept-done">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7l3 3 7-7" stroke="var(--sage)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                Specification approved
              </div>
            </AgentMessage>
            <PhaseDivider from="Simulation specification" to="Case building"/>
            <AgentMessage>
              <p className="md-p" style={{ fontSize: 14 }}>I've started writing the case files from the spec. Each finished phase drops its outputs into the project tree on the left — click any file to preview it here on the right.</p>
              <div className="event-history">
                <EventLine text="Wrote controlDict, fvSchemes"/>
              </div>
            </AgentMessage>
            <AgentMessage streaming={true}>
              <EventLine text="Using generate_case_files…"/>
              <EventLine text="Wrote fvSolution"/>
            </AgentMessage>
          </div>
        </div>
        <Composer placeholder="Ask about a file, or pause the agent…"/>
      </div>
      <div className="resize-handle" onMouseDown={onMouseDown}>
        <div className="resize-grip"/>
      </div>
      <SpecPanel
        project={projectTitle}
        subfolder={selectedFile?.subfolderName}
        file={selectedFile}
      />
    </div>
  );
}



// ─── Approval shelf variants ──────────────────────────────
// Persistent affordance shown above the composer when approval is pending.
// The inline accept-panel in chat history stays put as the "moment the agent
// asked"; this shelf is the ever-present way to act on that ask.

function ApprovalShelfV1({ onApprove }) {
  return (
    <div className="shelf shelf-v1">
      <span className="shelf-dot"/>
      <span className="shelf-text">Approval pending</span>
      <button className="shelf-btn shelf-btn-ghost" onClick={onApprove}>Approve</button>
    </div>
  );
}

function ApprovalShelfV2({ onApprove }) {
  return (
    <div className="shelf shelf-v2">
      <span className="shelf-pill">
        <span className="shelf-pill-dot"/>
        Approval pending
      </span>
      <span className="shelf-spacer"/>
      <button className="shelf-btn shelf-btn-neutral" onClick={onApprove}>Approve</button>
    </div>
  );
}

function ApprovalShelfV3({ onApprove }) {
  return (
    <div className="shelf shelf-v3">
      <div className="shelf-compound">
        <span className="shelf-compound-label">
          <span className="shelf-pill-dot"/>
          Approval pending
        </span>
        <button className="shelf-compound-btn" onClick={onApprove}>Approve</button>
      </div>
    </div>
  );
}

function ApprovalShelfV4({ onApprove }) {
  return (
    <div className="shelf shelf-v4">
      <span className="shelf-helper">Approval pending</span>
      <button className="shelf-btn shelf-btn-filled" onClick={onApprove}>
        <svg width="10" height="10" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 7l3 3 7-7"/></svg>
        Approve
      </button>
    </div>
  );
}

const SHELF_VARIANTS = [
  { id: "v2", label: "Pill + ghost",   component: ApprovalShelfV2, note: "Pill matches existing phase-chip vocabulary; lightest weight." },
  { id: "v1", label: "Tinted band",    component: ApprovalShelfV1, note: "Soft ochre tint — claims a small region as 'about a pending action'." },
  { id: "v3", label: "Compound chip",  component: ApprovalShelfV3, note: "Status and action fused into one object, right-aligned." },
  { id: "v4", label: "Filled button",  component: ApprovalShelfV4, note: "Most action-forward — filled ochre button, dim helper text." },
];

function ViewShelfVariants({ sidebarProps = {} }) {
  const [variantId, setVariantId] = useState("v2");
  const [approved, setApproved] = useState(false);
  const variant = SHELF_VARIANTS.find(v => v.id === variantId) || SHELF_VARIANTS[0];
  const ShelfComp = variant.component;

  const handleApprove = () => {
    setApproved(true);
    setTimeout(() => setApproved(false), 1800);
  };

  // Reset confirmation feedback when switching variants.
  const handleVariant = (id) => { setApproved(false); setVariantId(id); };

  return (
    <div className="app" style={{ height: "100%" }}>
      <Sidebar active="wing-airfoil" {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div>
            <div className="chat-title">NACA 0012 airfoil</div>
            <div className="chat-title-sub">Approval shelf · pick a variant to see it in context</div>
          </div>
          <div className="chat-top-right">
            <span className="chat-phase" style={{ background: "var(--ochre-tint)", color: "var(--ochre)" }}>
              <span className="phase-dot" style={{ background: "var(--ochre)" }}/>Case building
            </span>
          </div>
        </div>

        {/* Sub-tab selector — sits between chat-top and the scroll. */}
        <div className="variant-bar">
          <div className="variant-tabs" role="tablist">
            {SHELF_VARIANTS.map(v => (
              <button
                key={v.id}
                role="tab"
                aria-selected={v.id === variantId}
                className={`variant-tab ${v.id === variantId ? "is-active" : ""}`}
                onClick={() => handleVariant(v.id)}
              >
                {v.label}
              </button>
            ))}
          </div>
          <span className="variant-note">{variant.note}</span>
        </div>

        <div className="chat-scroll" style={{ overflowY: "auto" }}>
          <div className="chat-inner">
            <AgentMessage>
              <div className="accept accept-done">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7l3 3 7-7" stroke="var(--sage)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                Specification approved
              </div>
            </AgentMessage>
            <PhaseDivider from="Simulation specification" to="Case building"/>

            <AgentMessage>
              <p className="md-p" style={{ fontSize: 14 }}>
                Case files are ready — <code className="md-inline-code">controlDict</code>, <code className="md-inline-code">fvSchemes</code>, <code className="md-inline-code">fvSolution</code>, plus the boundary patches. The mesh next will be a C-grid with y⁺ ≈ 1.
              </p>
              <p className="md-p" style={{ fontSize: 14 }}>Ready to start meshing — should I proceed?</p>
              {/* Historical accept-panel: muted, shows the moment the agent asked */}
              <div className="accept accept-historical">
                <span className="accept-row-icon">
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="7" cy="7" r="5.5"/><path d="M7 4.2v3.2M7 9.7v.01"/></svg>
                </span>
                Asked about case specification — waiting on you
              </div>
            </AgentMessage>

            <UserBubble>What's the y⁺ across the airfoil? I want to make sure we're below 1 in the leading-edge region.</UserBubble>

            <AgentMessage>
              <div className="event-history">
                <EventLine text="Using inspect_mesh…"/>
              </div>
              <p className="md-p" style={{ fontSize: 14 }}>
                Wall y⁺ across the airfoil sits between <strong>0.6 and 1.1</strong>. The leading edge is at the lower end (around 0.6–0.8) thanks to the chordwise refinement; the maximum (~1.1) is around 70% chord on the suction side. That's within target for the SST model.
              </p>
              <p className="md-p" style={{ fontSize: 14 }}>Anything else you want to check before approving?</p>
            </AgentMessage>
          </div>
        </div>

        {approved
          ? <div className="shelf shelf-confirmed"><svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="var(--sage)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 7l3 3 7-7"/></svg>Approved · starting meshing</div>
          : <ShelfComp onApprove={handleApprove}/>}

        <Composer placeholder="Ask another question…"/>
      </div>
    </div>
  );
}



function ViewTrace({ sidebarProps = {} }) {
  // Toggle to demonstrate the live state — flips the trailing tool call's
  // status between "running" and "done". The streamline pulse plays while
  // running; once done the chevron returns and the row becomes expandable.
  const [running, setRunning] = useState(true);
  const toggleRunning = () => setRunning(v => !v);

  // ─── Demo payloads ────────────────────────────────────────────────────
  // All payloads are static demo data. The DictView highlighter renders the
  // JSON-ish input shape and the comment-bearing output shape consistently.

  // Round 1 — boundary layer + first cell height + scheme picking
  const REASONING_BL = `For an SST k–ω model on the airfoil surface I want y⁺ ≈ 1 in the leading-edge region. The chord Reynolds is 6 × 10⁶, so I'll use the flat-plate correlation as a first estimate.

From Schlichting, the friction coefficient at Re_x = 6 × 10⁶ is around C_f = 0.00295. That gives a wall shear stress τ_w ≈ ½ ρ U² · C_f and a friction velocity u_τ = √(τ_w/ρ).

For y⁺ = 1: y = ν / u_τ. Plugging in air at sea level (ν ≈ 1.5 × 10⁻⁵), I get a first cell height around 7 × 10⁻⁶ m. Let me run the calc to confirm before committing.`;

  const CELL_HEIGHT_INPUT = `{
    Re             6e6,
    chord          1.0,
    nu             1.5e-5,
    rho            1.225,
    y_plus_target  1.0
}`;
  const CELL_HEIGHT_OUTPUT = `// Result
first_cell_height   7.43e-6 m
friction_velocity   2.02 m/s
wall_shear_stress   5.00 Pa
C_f                 0.00295

// Notes
// Flat-plate estimate; actual y+ on the airfoil
// will vary 0.6–1.1 depending on chordwise station.`;

  const PICK_SCHEMES_INPUT = `{
    solver        "simpleFoam",
    turbulence    "kOmegaSST",
    flow_regime   "subsonic_attached",
    second_order  true
}`;
  const PICK_SCHEMES_OUTPUT = `// Recommended numerical schemes
ddtSchemes        steadyState
gradSchemes       Gauss linear
divSchemes        bounded Gauss linearUpwind
laplacianSchemes  Gauss linear corrected
snGradSchemes     corrected

// Notes
// linearUpwind for momentum gives second-order
// accuracy without oscillations near the LE.`;

  // Round 2 — patches + control dict
  const PATCHES_INPUT = `{
    geometry         "naca0012.stl",
    angle_of_attack  5.0,
    velocity         15.0,
    domain_radius    20  // chords
}`;
  const PATCHES_OUTPUT = `// Boundary patches
inlet         freestream  U = (14.94 1.31 0)
outlet        zeroGradient
airfoil       noSlip wall functions
far_field     symmetry
front, back   empty   // 2D case`;

  const CONTROL_DICT_INPUT = `{
    solver           "simpleFoam",
    end_iteration    2000,
    write_interval   200,
    function_objects ["forceCoeffs", "residuals"]
}`;
  const CONTROL_DICT_OUTPUT = `// Wrote system/controlDict (47 lines)
application       simpleFoam
startFrom         startTime
endTime           2000
deltaT            1
writeControl      timeStep
writeInterval     200

functions
{
    forceCoeffs   { type forceCoeffs;  ... }
    residuals     { type residuals;    ... }
}`;

  // Round 3 — the in-flight tool, writing fvSchemes and fvSolution
  const SOLVER_FILES_INPUT = `{
    schemes          (from pick_numerical_schemes),
    p_solver         "GAMG",
    U_solver         "smoothSolver",
    relaxation       { p: 0.3, U: 0.7 },
    residual_target  1e-5
}`;
  const SOLVER_FILES_OUTPUT = `// Wrote 2 files
fvSchemes      38 lines
fvSolution     62 lines

// SIMPLE residual targets
p              1e-5
U              1e-5
"(k|omega)"    1e-5`;

  return (
    <div className="app" style={{ height: "100%" }}>
      <Sidebar active="wing-airfoil" {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div>
            <div className="chat-title">NACA 0012 airfoil</div>
            <div className="chat-title-sub">Trace · click any reasoning or tool call to expand</div>
          </div>
          <div className="chat-top-right">
            <button className="demo-trigger" onClick={toggleRunning}>
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 3l6 6M3 9l6-6"/></svg>
              {running ? "Finish in-flight call" : "Replay in-flight"}
            </button>
            <span className="chat-phase" style={{ background: "var(--ochre-tint)", color: "var(--ochre)" }}>
              <span className="phase-dot" style={{ background: "var(--ochre)" }}/>Case building
            </span>
          </div>
        </div>

        <div className="chat-scroll" style={{ overflowY: "auto" }}>
          <div className="chat-inner">
            <UserBubble>Build the case files for the NACA 0012 run we specced — k–ω SST, Re = 6 × 10⁶, α = 5°.</UserBubble>

            <AgentMessage>
              {/* Round 1 — three events, then a text reply summarising what was figured out */}
              <p className="md-p" style={{ fontSize: 14 }}>On it. I'll work out the wall resolution and pick numerical schemes first, then start writing the case.</p>
              <div className="event-history">
                <ExpandableEvent
                  kind="thinking"
                  label="Thinking about boundary layer resolution"
                  reasoning={REASONING_BL}
                />
                <ExpandableEvent
                  kind="tool"
                  label="Using compute_first_cell_height"
                  input={CELL_HEIGHT_INPUT}
                  output={CELL_HEIGHT_OUTPUT}
                />
                <ExpandableEvent
                  kind="tool"
                  label="Using pick_numerical_schemes"
                  input={PICK_SCHEMES_INPUT}
                  output={PICK_SCHEMES_OUTPUT}
                />
              </div>
              <p className="md-p" style={{ fontSize: 14 }}>
                First cell height of <strong>7.4 × 10⁻⁶ m</strong> gives y⁺ ≈ 1 at the leading edge — within target for SST. For schemes I'll use bounded <code className="md-inline-code">linearUpwind</code> on momentum to keep second-order accuracy without oscillations near the LE.
              </p>

              {/* Round 2 — two more events, then a text reply about the case state */}
              <div className="event-history">
                <ExpandableEvent
                  kind="tool"
                  label="Using setup_boundary_patches"
                  input={PATCHES_INPUT}
                  output={PATCHES_OUTPUT}
                />
                <ExpandableEvent
                  kind="tool"
                  label="Using write_control_dict"
                  input={CONTROL_DICT_INPUT}
                  output={CONTROL_DICT_OUTPUT}
                  workspaceLink={{ label: "Case", subfolderId: "case" }}
                />
              </div>
              <p className="md-p" style={{ fontSize: 14 }}>
                Domain is set as a 20-chord C-grid with <code className="md-inline-code">far_field</code> as symmetry, and <code className="md-inline-code">controlDict</code> is written with force-coefficient and residual function objects. One last step — solver settings.
              </p>

              {/* Round 3 — single in-flight tool that flips to done via the header button */}
              <div className="event-history">
                <ExpandableEvent
                  kind="tool"
                  label={running ? "Using write_solver_files…" : "Using write_solver_files"}
                  status={running ? "running" : "done"}
                  input={SOLVER_FILES_INPUT}
                  output={SOLVER_FILES_OUTPUT}
                  workspaceLink={{ label: "Case", subfolderId: "case" }}
                  defaultExpanded={!running}
                />
              </div>
              {!running && (
                <p className="md-p" style={{ fontSize: 14 }}>
                  Case files are ready — <code className="md-inline-code">controlDict</code>, <code className="md-inline-code">fvSchemes</code>, <code className="md-inline-code">fvSolution</code>, plus the boundary patches. Approve to start meshing?
                </p>
              )}
            </AgentMessage>
          </div>
        </div>

        <Composer placeholder="Ask a follow-up about the case…"/>
      </div>
    </div>
  );
}




function ViewTimeline({ sidebarProps = {} }) {
  // Walks through five phases of an agent turn so you can watch the loader
  // handoff land in real time. Phase index 0..4. A phase advances either via
  // the Step button (manual) or via auto-advance. Auto-advance pauses on the
  // last phase so the final state is examinable.
  const PHASES = [
    { key: "wait",      label: "Phase 1 · Initial wait" },
    { key: "first",     label: "Phase 2 · First event running" },
    { key: "between",   label: "Phase 3 · Mid-stream" },
    { key: "final",     label: "Phase 4 · Final reply landing" },
    { key: "done",      label: "Phase 5 · Turn complete" },
  ];
  const [phase, setPhase] = useState(0);
  const [autoplay, setAutoplay] = useState(true);

  React.useEffect(() => {
    if (!autoplay) return;
    if (phase >= PHASES.length - 1) return; // pause at end
    const t = setTimeout(() => setPhase(p => p + 1), 2200);
    return () => clearTimeout(t);
  }, [phase, autoplay]);

  const reset = () => { setPhase(0); setAutoplay(true); };
  const step = () => { setAutoplay(false); setPhase(p => Math.min(p + 1, PHASES.length - 1)); };

  // ─── Per-phase event states ──────────────────────────────
  // For each phase we describe what the avatar shows and what status each of
  // the three event rows has. "hidden" means the row hasn't rendered yet.
  const phaseStates = {
    wait:    { streaming: true,  events: ["hidden", "hidden", "hidden"], showFinal: false },
    first:   { streaming: false, events: ["running", "hidden", "hidden"], showFinal: false },
    between: { streaming: false, events: ["done", "running", "hidden"], showFinal: false },
    final:   { streaming: false, events: ["done", "done", "running"],   showFinal: false },
    done:    { streaming: false, events: ["done", "done", "done"],      showFinal: true  },
  };
  const state = phaseStates[PHASES[phase].key];

  // The "running" status flag from the demo, mapped onto each event by index.
  const eventRow = (i, eventDef) => {
    const status = state.events[i];
    if (status === "hidden") return null;
    return (
      <ExpandableEvent
        key={i}
        kind={eventDef.kind}
        label={status === "running" ? `${eventDef.runningLabel}…` : eventDef.doneLabel}
        status={status}
        reasoning={eventDef.reasoning}
        input={eventDef.input}
        output={eventDef.output}
      />
    );
  };

  const EVENTS = [
    {
      kind: "thinking",
      runningLabel: "Thinking through the approach",
      doneLabel: "Thinking through the approach",
      reasoning: "Let me sketch the steady-state setup. With Re = 6 × 10⁶ and α = 5°, attached flow is reasonable everywhere on the airfoil — no separation expected — so simpleFoam with k–ω SST is the right choice. I'll target y⁺ ≈ 1 at the wall.",
    },
    {
      kind: "tool",
      runningLabel: "Using compute_first_cell_height",
      doneLabel: "Using compute_first_cell_height",
      input: `{ Re: 6e6, chord: 1.0, y_plus_target: 1.0 }`,
      output: `// Result\nfirst_cell_height   7.43e-6 m`,
    },
    {
      kind: "tool",
      runningLabel: "Using write_solver_files",
      doneLabel: "Using write_solver_files",
      input: `{ solver: "simpleFoam", turbulence: "kOmegaSST" }`,
      output: `// Wrote 3 files\ncontrolDict   47 lines\nfvSchemes     38 lines\nfvSolution    62 lines`,
    },
  ];

  return (
    <div className="app" style={{ height: "100%" }}>
      <Sidebar active="wing-airfoil" {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div>
            <div className="chat-title">NACA 0012 airfoil</div>
            <div className="chat-title-sub">Loader handoff · {PHASES[phase].label}</div>
          </div>
          <div className="chat-top-right">
            <button className="demo-trigger" onClick={reset}>
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M2 6 a4 4 0 1 1 1.2 2.83 M2 8.5 V6 H4.5"/></svg>
              Restart
            </button>
            <button className="demo-trigger" onClick={step} disabled={phase >= PHASES.length - 1}>
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 3l4 3-4 3M8 3v6"/></svg>
              Step
            </button>
            <span className="chat-phase" style={{ background: "var(--ochre-tint)", color: "var(--ochre)" }}>
              <span className="phase-dot" style={{ background: "var(--ochre)" }}/>Case building
            </span>
          </div>
        </div>

        {/* Phase progress strip — purely visual; reinforces where in the
            sequence you are. Filled dots for completed/current phases. */}
        <div className="timeline-strip">
          {PHASES.map((p, i) => (
            <span key={p.key} className={`timeline-step ${i <= phase ? "is-on" : ""} ${i === phase ? "is-current" : ""}`}>
              <span className="timeline-step-dot"/>
              <span className="timeline-step-label">{p.label.split(" · ")[1]}</span>
            </span>
          ))}
        </div>

        <div className="chat-scroll" style={{ overflowY: "auto" }}>
          <div className="chat-inner">
            <UserBubble>Build the case files — k–ω SST, Re = 6 × 10⁶, α = 5°.</UserBubble>

            <AgentMessage streaming={state.streaming}>
              {!state.streaming && (
                <>
                  {/* No intro prose — in a real turn the first event lands
                      with the agent message otherwise empty, so the avatar
                      loader has to fade as the small glyph appears on the
                      event row. That's the transition we want to see. */}
                  <div className="event-history">
                    {EVENTS.map((e, i) => eventRow(i, e))}
                  </div>
                  {state.showFinal && (
                    <p className="md-p" style={{ fontSize: 14 }}>
                      Case files are ready — first cell height of <strong>7.4 × 10⁻⁶ m</strong> hits y⁺ ≈ 1. Approve to start meshing?
                    </p>
                  )}
                </>
              )}
            </AgentMessage>
          </div>
        </div>

        <Composer
          disabled={phase < PHASES.length - 1}
          placeholder={phase < PHASES.length - 1 ? "Agent is working…" : "Ask a follow-up about the case…"}
        />
      </div>
    </div>
  );
}



function ViewNewSim({ sidebarProps = {} }) {
  const [name, setName] = useState("");
  const [level, setLevel] = useState(null);
  const levels = [
    { id: "beginner", label: "Beginner", desc: "I'm new to CFD — guide me through this" },
    { id: "intermediate", label: "Intermediate", desc: "I have working CFD knowledge" },
    { id: "expert", label: "Expert", desc: "I know exactly what I need" },
  ];
  return (
    <div className="app" style={{height:"100%"}}>
      <Sidebar active="" {...sidebarProps}/>
      <div className="chat-col">
        <div className="chat-top">
          <div><div className="chat-title">New simulation</div><div className="chat-title-sub">Set up your project</div></div>
        </div>
        <div className="chat-scroll" style={{overflowY:"auto"}}>
          <div className="chat-inner" style={{paddingTop:48, maxWidth:520}}>
            <div className="new-sim-mark"><BrandMark size={36}/></div>
            <h2 className="new-sim-title">Start a new simulation</h2>
            <p className="new-sim-sub">Name your project and choose your experience level. This helps the agent calibrate its questions.</p>

            <div className="new-sim-field">
              <label className="new-sim-label">Project name</label>
              <input className="new-sim-input" type="text" placeholder="e.g. NACA 0012 airfoil study" value={name} onChange={e => setName(e.target.value)}/>
            </div>

            <div className="new-sim-field">
              <label className="new-sim-label">Experience level</label>
              <div className="new-sim-levels">
                {levels.map(l => (
                  <button key={l.id} className={`new-sim-level ${level === l.id ? "is-active" : ""}`} onClick={() => setLevel(l.id)}>
                    <span className="new-sim-level-name">{l.label}</span>
                    <span className="new-sim-level-desc">{l.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <button className="new-sim-start" disabled={!name.trim() || !level}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M2 7h10M8 3l4 4-4 4"/></svg>
              Start simulation
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// APP — Tab navigation
// ═══════════════════════════════════════════════════════════

const VIEWS = [
  { id:"new", label:"New Simulation", icon:"+" },
  { id:"chat", label:"Chat", icon:"💬" },
  { id:"spec", label:"Spec Review", icon:"📋" },
  { id:"phase", label:"Phase Transition", icon:"→" },
  { id:"workspace", label:"Workspace", icon:"▸" },
  { id:"shelf", label:"Approval Shelf", icon:"✓" },
  { id:"trace", label:"Trace", icon:"~" },
  { id:"timeline", label:"Loader Handoff", icon:"◆" },
];

const ACCENTS = {
  terracotta: { primary:"#B8553C", primary2:"#D97A5F", tint:"#F3DFD4" },
  sage: { primary:"#6E8A6A", primary2:"#8CA686", tint:"#DDE5D3" },
  indigo: { primary:"#4F5B92", primary2:"#6A79B3", tint:"#DCE0EE" },
  ochre: { primary:"#B4862E", primary2:"#D1A34F", tint:"#F1E4C0" },
};

export default function App() {
  const [view, setView] = useState("timeline");
  const [accent, setAccent] = useState("indigo");
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    const a = ACCENTS[accent];
    document.documentElement.style.setProperty("--terracotta", a.primary);
    document.documentElement.style.setProperty("--terracotta-2", a.primary2);
    document.documentElement.style.setProperty("--terracotta-tint", a.tint);
  }, [accent]);

  const sidebarProps = {
    darkMode, onToggleDark: () => setDarkMode(!darkMode),
    accent, onAccent: setAccent, accents: ACCENTS,
    onNewSim: () => setView("new"),
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

        :root {
          --paper: #F3F1ED; --paper-2: #ECEAE4; --paper-3: #E2E0D9;
          --card: #F8F7F3; --ink: #2A2620; --ink-2: #5B5247; --ink-3: #8A8078; --ink-4: #B5ADA2;
          --rule: #D5CFC4;
          --terracotta: #4F5B92; --terracotta-2: #6A79B3; --terracotta-tint: #DCE0EE;
          --ochre: #C69A3E; --ochre-tint: #F1E4C0;
          --sage: #7F8F6A; --sage-tint: #E1E4CF;
          --user-bubble: #E5E2DA; --user-bubble-border: #D5D1C7;
          --shadow-sm: 0 1px 2px rgba(40,30,20,0.04), 0 1px 0 rgba(40,30,20,0.02);
          --shadow-md: 0 2px 6px rgba(40,30,20,0.06), 0 6px 18px rgba(40,30,20,0.05);
          --shadow-lg: 0 12px 40px rgba(40,30,20,0.12), 0 2px 6px rgba(40,30,20,0.06);
          --font-sans: "Inter Tight", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
          --r-sm: 6px; --r-md: 10px; --r-lg: 14px; --r-xl: 20px;
        }

        .theme-dark {
          --paper: #1A1917; --paper-2: #131211; --paper-3: #24231F;
          --card: #201F1B; --ink: #ECE6D8; --ink-2: #B3AA9A; --ink-3: #8A8078; --ink-4: #4A443D;
          --rule: #2C2822;
          --user-bubble: #292722; --user-bubble-border: #38342B;
        }

        * { box-sizing: border-box; margin: 0; }
        body { font-family: var(--font-sans); color: var(--ink); background: var(--paper); -webkit-font-smoothing: antialiased; }

        /* ─── Scrollbars ───────────────────────────────────────────────
           Default: slim, low-contrast, fades into the surrounding paper.
           The thumb appears only when the scroll container is hovered or
           actively scrolled — at rest the bar effectively disappears.
           Firefox uses scrollbar-width/scrollbar-color (no hover state),
           WebKit/Blink lean on ::-webkit-scrollbar pseudo-elements. */
        * { scrollbar-width: thin; scrollbar-color: transparent transparent; }
        *:hover { scrollbar-color: color-mix(in srgb, var(--ink-3) 35%, transparent) transparent; }
        *::-webkit-scrollbar { width: 8px; height: 8px; background: transparent; }
        *::-webkit-scrollbar-track { background: transparent; }
        *::-webkit-scrollbar-thumb { background: transparent; border-radius: 999px; border: 2px solid transparent; background-clip: padding-box; transition: background-color .2s; }
        *:hover::-webkit-scrollbar-thumb { background-color: color-mix(in srgb, var(--ink-3) 30%, transparent); background-clip: padding-box; }
        *::-webkit-scrollbar-thumb:hover { background-color: color-mix(in srgb, var(--ink-3) 60%, transparent); background-clip: padding-box; }
        *::-webkit-scrollbar-corner { background: transparent; }
        /* Suppress horizontal scrollbars globally — content that would cause
           horizontal overflow uses hidden overflow + ellipsis or wraps. The
           main chat column still scrolls vertically; the workaround is to
           use the .scroll-x-hidden helper below where horizontal overflow
           is genuinely intended (e.g., the wide nav tabs row). */
        .scroll-x-hidden { overflow-x: auto; scrollbar-width: none; }
        .scroll-x-hidden::-webkit-scrollbar { display: none; }
        /* Fully invisible scrollbars — used by the sidebar and any other
           container small enough that hovering to scroll is fine. */
        .scroll-hidden { scrollbar-width: none; }
        .scroll-hidden::-webkit-scrollbar { display: none; width: 0; height: 0; }

        /* ─── Layout ─── */
        .app { display: grid; grid-template-columns: auto 1fr; height: 100%; width: 100%; background: var(--paper); color: var(--ink); font-family: var(--font-sans); font-size: 15px; line-height: 1.55; }
        .app.has-spec { grid-template-columns: auto 1fr 340px; }

        /* ─── Sidebar ─── */
        .sb { background: var(--paper-2); border-right: 1px solid var(--rule); display: flex; flex-direction: column; overflow: hidden; width: 240px; padding: 18px 14px 12px; }
        .sb.is-collapsed { width: 48px; padding: 0; }
        .sb-rail { width: 48px; height: 100%; display: flex; flex-direction: column; align-items: center; padding: 14px 0 10px; gap: 18px; background: transparent; border: 0; cursor: pointer; color: var(--ink-2); }
        .sb-rail:hover { background: var(--paper-3); color: var(--ink); }
        .sb-rail-brand { display: flex; align-items: center; justify-content: center; }
        .sb-rail-icons { display: flex; flex-direction: column; gap: 6px; align-items: center; }
        .sb-rail-btn { width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: var(--ink-3); }
        .sb-rail-chev { margin-top: auto; color: var(--ink-3); opacity: 0.6; }
        .sb-head { margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; }
        .sb-toggle { width: 24px; height: 24px; background: transparent; border: 1px solid var(--rule); border-radius: 6px; display: flex; align-items: center; justify-content: center; color: var(--ink-3); cursor: pointer; padding: 0; }
        .sb-toggle:hover { color: var(--ink); border-color: var(--ink-4); background: var(--paper); }
        .sb-brand { display: flex; align-items: center; gap: 10px; padding: 4px 6px; }
        .sb-brand-name { font-weight: 600; letter-spacing: -0.01em; font-size: 15px; }
        .sb-brand-sub { font-size: 11px; color: var(--ink-3); letter-spacing: 0.02em; }
        .sb-new { display: flex; align-items: center; gap: 8px; padding: 9px 12px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-md); color: var(--ink); font-family: inherit; font-size: 13.5px; font-weight: 500; cursor: pointer; margin-bottom: 20px; }
        .sb-new:hover { background: var(--paper); border-color: var(--ink-4); }
        .sb-section { flex: 1; overflow-y: auto; }
        .sb-section-label { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); padding: 0 6px 8px; }
        .sb-proj { display: flex; gap: 10px; padding: 9px 10px; border-radius: var(--r-md); cursor: pointer; margin-bottom: 2px; }
        .sb-proj:hover { background: var(--paper-3); }
        .sb-proj.is-active { background: var(--paper-3); }
        .sb-proj-icon { width: 16px; flex: 0 0 16px; display: flex; align-items: center; margin-top: 1px; }
        .sb-proj-body { min-width: 0; flex: 1; }
        .sb-proj-name { font-size: 13.5px; color: var(--ink); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .sb-proj-meta { font-size: 11px; color: var(--ink-3); display: flex; gap: 6px; align-items: center; margin-top: 1px; }
        .dot-sep { opacity: 0.5; }
        .sb-foot { padding-top: 12px; border-top: 1px solid var(--rule); display: flex; flex-direction: column; gap: 12px; }
        .sb-setting { display: flex; flex-direction: column; gap: 5px; }
        .sb-setting-label { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }
        .sb-theme-toggle { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; background: var(--paper); border: 1px solid var(--rule); border-radius: 6px; font: inherit; font-size: 11.5px; color: var(--ink-2); cursor: pointer; transition: all .12s; }
        .sb-theme-toggle:hover { background: var(--paper-3); border-color: var(--ink-4); color: var(--ink); }
        .sb-accent-row { display: flex; gap: 5px; }
        .sb-accent-dot { width: 18px; height: 18px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; transition: transform .1s; }
        .sb-accent-dot:hover { transform: scale(1.15); }
        .sb-accent-dot.is-active { border-color: var(--ink); box-shadow: 0 0 0 2px var(--paper-2); }

        /* ─── Chat ─── */
        .chat-col { display: grid; grid-template-rows: auto 1fr auto; overflow: hidden; min-width: 0; position: relative; }
        .chat-top { padding: 14px 28px; border-bottom: 1px solid var(--rule); display: flex; align-items: center; justify-content: space-between; background: var(--paper); }
        .chat-title { font-weight: 600; font-size: 15px; letter-spacing: -0.01em; }
        .chat-title-sub { font-size: 11.5px; color: var(--ink-3); margin-top: 2px; }
        .chat-top-right { display: flex; align-items: center; gap: 8px; }
        .chat-phase { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--terracotta-tint); color: var(--terracotta); border-radius: 100px; font-size: 11.5px; font-weight: 500; }
        .chat-phase .phase-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--terracotta); }
        .chat-scroll { overflow-y: auto; padding: 28px 0 20px; }
        .chat-inner { max-width: 700px; margin: 0 auto; padding: 0 28px; display: flex; flex-direction: column; gap: 22px; }

        /* ─── Messages ─── */
        .msg { display: flex; gap: 14px; }
        .msg.user { justify-content: flex-end; }
        .bubble { max-width: 560px; padding: 12px 16px; border-radius: 14px; }
        .user-bubble { background: var(--user-bubble); border: 1px solid var(--user-bubble-border); color: var(--ink); border-top-right-radius: 4px; font-size: 14.5px; line-height: 1.55; }
        .agent-mark { width: 28px; height: 28px; flex: 0 0 28px; display: flex; align-items: center; justify-content: center; margin-top: 2px; position: relative; }
        .agent-mark-loader, .agent-mark-brand { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; transition: opacity 280ms ease; }
        .agent-mark .agent-mark-loader { opacity: 0; }
        .agent-mark .agent-mark-brand  { opacity: 1; }
        .agent-mark.is-streaming .agent-mark-loader { opacity: 1; }
        .agent-mark.is-streaming .agent-mark-brand  { opacity: 0; }
        .agent-body { flex: 1; min-width: 0; padding-top: 3px; }
        .agent-body > * + * { margin-top: 10px; }

        /* ─── Event lines (simplified status) ─── */
        .event-line { font-size: 13px; font-style: italic; color: var(--ink-3); padding: 1px 0; line-height: 1.5; }
        .event-history { display: flex; flex-direction: column; gap: 1px; margin-bottom: 6px; padding-left: 1px; }
        .status-text { letter-spacing: -0.005em; }


        /* ─── Markdown ─── */
        .md { color: var(--ink); font-size: 14px; line-height: 1.62; }
        .md > * + * { margin-top: 12px; }
        .md-h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 4px; line-height: 1.2; }
        .md-h2 { font-size: 14px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-2); margin: 18px 0 4px; }
        .md-p { margin: 0; }
        .md-ul { margin: 0; padding-left: 18px; list-style: none; }
        .md-li { position: relative; margin: 4px 0; padding-left: 14px; }
        .md-li::before { content: ""; position: absolute; left: 0; top: 10px; width: 6px; height: 1.5px; background: var(--terracotta); }
        .md-li-nested { padding-left: 22px; color: var(--ink-2); font-size: 13.5px; }
        .md-li-nested::before { left: 8px; background: var(--ink-4); }
        .md-inline-code { font-family: var(--font-mono); font-size: 12.5px; background: var(--paper-3); padding: 1px 6px; border-radius: 4px; color: var(--terracotta); }

        /* ─── Resize handle ─── */
        .resize-handle { width: 8px; cursor: col-resize; display: flex; align-items: center; justify-content: center; position: relative; z-index: 10; margin: 0 -4px; }
        .resize-handle:hover .resize-grip, .resize-handle:active .resize-grip { opacity: 1; background: var(--terracotta); }
        .resize-grip { width: 3px; height: 40px; border-radius: 3px; background: var(--rule); opacity: 0.6; transition: opacity .15s, background .15s; }

        /* ─── Spec panel ─── */
        .spec-panel { border-left: 1px solid var(--rule); background: var(--paper-2); display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
        .spec-panel-head { padding: 14px 18px; border-bottom: 1px solid var(--rule); display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; background: var(--paper); }
        .spec-panel-kicker { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }
        .spec-panel-title { font-size: 13.5px; font-weight: 600; margin-top: 2px; color: var(--ink); }
        .spec-panel-body { flex: 1; overflow-y: auto; padding: 18px 20px; }
        .spec-panel-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 28px; gap: 8px; text-align: center; color: var(--ink-3); }
        .spec-panel-empty-title { font-size: 14px; font-weight: 500; color: var(--ink-2); margin-top: 6px; }
        .spec-panel-empty-sub { font-size: 12.5px; color: var(--ink-3); max-width: 240px; line-height: 1.5; }

        /* ─── Project tree (subfolders + files under active project) ─── */
        .sb-tree { position: relative; padding-left: 22px; margin: 2px 0 6px 4px; }
        .sb-tree::before { content: ""; position: absolute; left: 14px; top: 4px; bottom: 4px; width: 1px; background: var(--rule); }
        .sb-sub { margin-bottom: 1px; }
        .sb-sub-row { display: flex; align-items: center; gap: 7px; padding: 5px 8px; width: 100%; background: transparent; border: 0; border-radius: 6px; font: inherit; cursor: pointer; color: var(--ink); text-align: left; }
        .sb-sub-row:hover { background: var(--paper-3); }
        .sb-chev { display: inline-flex; align-items: center; justify-content: center; color: var(--ink-3); flex: 0 0 9px; width: 9px; height: 9px; }
        .sb-sub-icon { display: inline-flex; align-items: center; flex: 0 0 12px; }
        .sb-sub-name { font-size: 12.5px; font-weight: 500; }
        .sb-sub-pulse { margin-left: auto; display: inline-flex; align-items: center; }
        .sb-files { display: flex; flex-direction: column; padding: 1px 0; }
        .sb-file { display: flex; align-items: center; padding: 4px 8px 4px 32px; background: transparent; border: 0; border-radius: 6px; width: 100%; text-align: left; font: inherit; cursor: pointer; color: var(--ink-2); position: relative; }
        .sb-file:hover { background: var(--paper-3); color: var(--ink); }
        .sb-file.is-mono .sb-file-name { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-2); }
        .sb-file.is-active { background: var(--paper-3); }
        .sb-file.is-active .sb-file-name { color: var(--ink); font-weight: 500; }
        .sb-file.is-active::before { content: ""; position: absolute; left: 20px; top: 50%; width: 6px; height: 1.5px; background: var(--terracotta); }
        .sb-file-name { font-size: 12.5px; line-height: 1.5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .sb-file-new { width: 5px; height: 5px; border-radius: 50%; background: var(--terracotta); margin-left: auto; flex: 0 0 5px; }

        /* ─── Dict view (config files) ─── */
        .dict-view { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.7; color: var(--ink-2); }
        .dict-line { white-space: pre; }
        .dict-line.is-comment { color: var(--ink-3); font-style: italic; }
        .dict-line.is-brace { color: var(--ink-4); }

        /* ─── Expandable event (Trace view) ─── */
        .xevent { display: flex; flex-direction: column; }
        .xevent-row { display: flex; align-items: center; gap: 8px; padding: 4px 6px; background: transparent; border: 0; border-radius: 5px; cursor: pointer; font: inherit; font-size: 12.5px; color: var(--ink-3); font-style: italic; text-align: left; transition: background .12s; }
        .xevent-row:hover:not(:disabled) { background: var(--paper-3); }
        .xevent-row:disabled { cursor: default; }
        .xevent-marker { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 14px; width: 14px; color: var(--ink-4); }
        /* When a tool/thinking row enters in the running state, briefly fade
           the streamline glyph in so it dovetails with the avatar loader's
           exit fade. Delay matches roughly half the avatar exit duration so
           the eye reads it as "loader left there, loader appeared here". */
        .xevent.is-running .xevent-marker { animation: xevent-marker-in 240ms ease 140ms both; }
        @keyframes xevent-marker-in { from { opacity: 0; } to { opacity: 1; } }
        .xevent-chev { transition: transform .15s ease; }
        .xevent-chev.is-open { transform: rotate(90deg); }
        .xevent-label { line-height: 1.4; }

        .xevent-body { margin: 4px 0 8px 18px; padding-left: 14px; border-left: 1px solid var(--rule); display: flex; flex-direction: column; gap: 6px; }
        .xevent-section-label { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; font-style: normal; margin-top: 4px; }
        .xevent-section-label:first-child { margin-top: 0; }
        .xevent-box { border: 1px solid var(--rule); border-radius: 6px; background: var(--paper-2); padding: 8px 10px; max-height: 160px; overflow-y: auto; overflow-x: hidden; position: relative; }
        .xevent-box-mono { font-family: var(--font-mono); font-size: 11.5px; line-height: 1.65; }
        .xevent-box-mono .dict-view { font-size: 11.5px; line-height: 1.65; }

        /* Inline reasoning prose: distinguished from the agent's main reply
           by a half-step smaller font and one notch dimmer color (--ink-2).
           Always shows fully when the event is expanded. */
        .xevent-prose { font-family: var(--font-sans); font-size: 12.5px; line-height: 1.6; color: var(--ink-2); }
        .xevent-prose p { margin: 0 0 8px; }
        .xevent-prose p:last-child { margin: 0; }
        .xevent-link { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; background: var(--paper-3); border: 1px solid var(--rule); border-radius: 6px; font-family: var(--font-mono); font-size: 11.5px; color: var(--terracotta); cursor: pointer; align-self: flex-start; transition: background .12s, border-color .12s; }
        .xevent-link:hover { background: var(--ochre-tint); border-color: var(--ochre); }
        .xevent-link svg { color: var(--ochre); }

        /* ─── Expandable event — inline variant (no boxes) ─── */
        /* Removed: the inline variant has been merged into ExpandableEvent's
           reasoning rendering, which now uses .xevent-prose with a soft cap. */

        /* ─── New-file toast ─── */
        .toast-stack { position: absolute; top: 64px; left: 24px; z-index: 50; display: flex; flex-direction: column; gap: 8px; pointer-events: none; max-width: 280px; }
        .toast { display: flex; align-items: center; gap: 10px; padding: 9px 14px 9px 12px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-md); box-shadow: var(--shadow-md); pointer-events: auto; cursor: pointer; font: inherit; text-align: left; color: inherit; min-width: 220px; animation: toast-in 240ms cubic-bezier(0.16, 1, 0.3, 1); }
        .toast:hover { border-color: var(--ink-4); background: var(--paper); }
        .toast.is-leaving { animation: toast-out 220ms ease-in forwards; }
        .toast-icon { display: inline-flex; align-items: center; flex: 0 0 14px; }
        .toast-text { display: flex; flex-direction: column; min-width: 0; }
        .toast-name { font-size: 13px; font-weight: 500; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.35; }
        .toast-sub { font-size: 11.5px; color: var(--ink-3); margin-top: 1px; }
        @keyframes toast-in { from { opacity: 0; transform: translate3d(-6px, -6px, 0); } to { opacity: 1; transform: translate3d(0, 0, 0); } }
        @keyframes toast-out { from { opacity: 1; transform: translate3d(0, 0, 0); } to { opacity: 0; transform: translate3d(-6px, -6px, 0); } }

        /* ─── Demo trigger button (Workspace view) ─── */
        .demo-trigger { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: transparent; border: 1px solid var(--rule); border-radius: 6px; font: inherit; font-size: 11.5px; color: var(--ink-3); cursor: pointer; transition: background .12s, color .12s, border-color .12s; }
        .demo-trigger:hover:not(:disabled) { background: var(--paper-3); color: var(--ink); border-color: var(--ink-4); }
        .demo-trigger:disabled { opacity: 0.45; cursor: default; }

        /* ─── Phase progress strip (Loader Handoff view) ─── */
        .timeline-strip { display: flex; align-items: center; gap: 18px; padding: 10px 18px; border-bottom: 1px solid var(--rule); background: var(--paper-2); }
        .timeline-step { display: inline-flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--ink-3); transition: color .2s; }
        .timeline-step-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--rule); transition: background .25s, transform .2s; flex: 0 0 7px; }
        .timeline-step.is-on { color: var(--ink-2); }
        .timeline-step.is-on .timeline-step-dot { background: var(--ochre); }
        .timeline-step.is-current { color: var(--ink); font-weight: 500; }
        .timeline-step.is-current .timeline-step-dot { background: var(--terracotta); transform: scale(1.25); }

        /* ─── Approval shelf (variants) ───
           All shelves sit between the chat-scroll and the composer. Border-top
           is the seam to the chat content; the composer's top edge sits below. */
        .shelf { font-family: var(--font-sans); }

        /* Variant 1 — tinted band, dot + text + button */
        .shelf-v1 { display: flex; align-items: center; gap: 10px; padding: 8px 16px; background: var(--ochre-tint); border-top: 1px solid color-mix(in srgb, var(--ochre) 25%, transparent); }
        .shelf-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ochre); flex: 0 0 6px; }
        .shelf-text { flex: 1; font-size: 12.5px; color: var(--ink); }

        /* Variant 2 — pill on left, ghost button on right */
        .shelf-v2 { display: flex; align-items: center; gap: 10px; padding: 8px 16px; border-top: 1px solid var(--rule); background: var(--paper-2); }
        .shelf-pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; background: var(--ochre-tint); color: var(--ochre); border-radius: 999px; font-size: 11px; font-weight: 500; }
        .shelf-pill-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--ochre); flex: 0 0 5px; }
        .shelf-spacer { flex: 1; }

        /* Variant 3 — compound chip (label fused to button) */
        .shelf-v3 { display: flex; justify-content: flex-end; padding: 9px 16px; border-top: 1px solid var(--rule); background: var(--paper-2); }
        .shelf-compound { display: inline-flex; align-items: stretch; border: 1px solid color-mix(in srgb, var(--ochre) 40%, transparent); border-radius: 999px; overflow: hidden; }
        .shelf-compound-label { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px 4px 11px; background: var(--ochre-tint); color: var(--ink); font-size: 12px; }
        .shelf-compound-btn { padding: 4px 14px; background: transparent; color: var(--ink); font-size: 12px; font-weight: 500; border: 0; border-left: 1px solid color-mix(in srgb, var(--ochre) 40%, transparent); cursor: pointer; font-family: inherit; transition: background .12s; }
        .shelf-compound-btn:hover { background: color-mix(in srgb, var(--ochre) 12%, transparent); }

        /* Variant 4 — filled button leads, dim helper text */
        .shelf-v4 { display: flex; align-items: center; gap: 10px; padding: 8px 16px; border-top: 1px solid var(--rule); background: var(--paper-2); }
        .shelf-helper { flex: 1; font-size: 12px; color: var(--ink-3); }

        /* Shared button styles used across variants */
        .shelf-btn { font-family: inherit; cursor: pointer; transition: background .12s, color .12s, border-color .12s; font-weight: 500; }
        .shelf-btn-ghost { padding: 5px 14px; font-size: 12px; border: 1px solid var(--ochre); background: transparent; color: var(--ink); border-radius: 6px; }
        .shelf-btn-ghost:hover { background: color-mix(in srgb, var(--ochre) 12%, transparent); }
        .shelf-btn-neutral { padding: 5px 14px; font-size: 12px; border: 1px solid var(--rule); background: var(--paper); color: var(--ink); border-radius: 6px; }
        .shelf-btn-neutral:hover { background: var(--ochre-tint); border-color: var(--ochre); }
        .shelf-btn-filled { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px 5px 10px; font-size: 12px; background: var(--ochre); color: #fff; border: 0; border-radius: 6px; }
        .shelf-btn-filled:hover { background: color-mix(in srgb, var(--ochre) 88%, black); }

        /* Post-approve confirmation — replaces the shelf for ~1.8s */
        .shelf-confirmed { display: flex; align-items: center; gap: 8px; padding: 9px 16px; border-top: 1px solid var(--rule); background: var(--sage-tint); color: var(--sage); font-size: 12.5px; font-weight: 500; }

        /* Historical accept-panel — same structure as .accept, dimmed to read
           as "this question was already asked, action lives on the shelf now". */
        .accept.accept-historical { background: var(--paper-3); border: 1px solid var(--rule); color: var(--ink-3); display: inline-flex; align-items: center; gap: 8px; padding: 6px 11px; border-radius: 8px; font-size: 12px; font-style: italic; }
        .accept.accept-historical .accept-row-icon { color: var(--ink-3); display: inline-flex; }

        /* ─── Variant sub-tab bar (Approval Shelf view only) ─── */
        .variant-bar { display: flex; align-items: center; gap: 14px; padding: 8px 18px; border-bottom: 1px solid var(--rule); background: var(--paper-2); }
        .variant-tabs { display: inline-flex; gap: 4px; }
        .variant-tab { padding: 4px 11px; font-size: 11.5px; background: transparent; border: 1px solid transparent; border-radius: 6px; color: var(--ink-3); font-family: inherit; cursor: pointer; transition: background .12s, color .12s, border-color .12s; }
        .variant-tab:hover { color: var(--ink); }
        .variant-tab.is-active { background: var(--paper); border-color: var(--rule); color: var(--ink); }
        .variant-note { font-size: 11.5px; color: var(--ink-3); font-style: italic; line-height: 1.45; flex: 1; min-width: 0; }

        /* ─── Accept ─── */
        .accept { font-size: 13.5px; }
        .accept-q { font-weight: 500; color: var(--ink); margin-bottom: 10px; }
        .accept-opts { display: flex; flex-direction: column; gap: 8px; }
        .accept-opt { display: flex; align-items: flex-start; gap: 12px; padding: 11px 14px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-md); cursor: pointer; text-align: left; font: inherit; color: inherit; transition: border-color .12s, background .12s; }
        .accept-opt:hover { border-color: var(--ink-4); background: var(--paper); }
        .accept-yes:hover { border-color: var(--sage); background: var(--sage-tint); }
        .accept-no:hover { border-color: var(--terracotta); }
        .opt-mark { color: var(--ink-3); font-size: 12px; line-height: 1.4; }
        .accept-yes:hover .opt-mark { color: var(--sage); }
        .accept-no:hover .opt-mark { color: var(--terracotta); }
        .opt-title { display: block; font-weight: 500; color: var(--ink); }
        .opt-sub { display: block; font-size: 11.5px; color: var(--ink-3); margin-top: 1px; }
        .accept-hint { margin-top: 10px; font-size: 11.5px; color: var(--ink-3); font-style: italic; }
        .accept-textarea { width: 100%; padding: 10px 12px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-md); font: inherit; font-size: 13.5px; color: var(--ink); resize: vertical; min-height: 72px; outline: none; }
        .accept-textarea:focus { border-color: var(--terracotta); box-shadow: 0 0 0 3px var(--terracotta-tint); }
        .accept-label { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; margin-bottom: 8px; }
        .accept-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
        .accept-done { display: inline-flex; align-items: center; gap: 8px; color: var(--sage); font-weight: 500; padding: 8px 12px; background: var(--sage-tint); border-radius: var(--r-md); }
        .btn-primary { padding: 8px 14px; background: var(--terracotta); color: #fff; border: 0; border-radius: var(--r-md); font: inherit; font-size: 13px; font-weight: 500; cursor: pointer; }
        .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-ghost { padding: 8px 14px; background: transparent; color: var(--ink-2); border: 1px solid var(--rule); border-radius: var(--r-md); font: inherit; font-size: 13px; cursor: pointer; }
        .btn-ghost:hover { background: var(--paper-3); }

        /* ─── Accept panel ─── */
        .accept-panel { max-width: 700px; margin: 0 auto; padding: 14px 16px; background: var(--card); border: 1px solid var(--terracotta); border-radius: var(--r-lg); box-shadow: var(--shadow-md); }
        .accept-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
        .accept-panel-title { font-size: 14px; font-weight: 600; color: var(--ink); }
        .accept-panel-close { width: 24px; height: 24px; background: transparent; border: 1px solid var(--rule); border-radius: 6px; display: flex; align-items: center; justify-content: center; color: var(--ink-3); cursor: pointer; padding: 0; }
        .accept-panel-exit { display: inline-flex; align-items: center; gap: 6px; background: transparent; border: 1px solid var(--rule); padding: 5px 10px; border-radius: 6px; font: inherit; font-size: 11.5px; color: var(--ink-3); cursor: pointer; white-space: nowrap; transition: background .12s, color .12s, border-color .12s; }
        .accept-panel-exit:hover { background: var(--paper-2); color: var(--ink); border-color: var(--ink-4); }
        .accept-panel-opts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .accept-panel-textarea { width: 100%; padding: 10px 12px; background: var(--paper); border: 1px solid var(--rule); border-radius: var(--r-md); font: inherit; font-size: 13.5px; color: var(--ink); resize: vertical; min-height: 72px; outline: none; }
        .accept-panel-textarea:focus { border-color: var(--terracotta); box-shadow: 0 0 0 3px var(--terracotta-tint); }
        .accept-panel-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
        .sp-btn { padding: 7px 12px; background: transparent; border: 1px solid var(--rule); border-radius: 6px; font: inherit; font-size: 12.5px; color: var(--ink-2); cursor: pointer; }
        .sp-btn:hover { background: var(--paper-3); color: var(--ink); }
        .sp-btn.primary { background: var(--terracotta); border-color: var(--terracotta); color: #fff; }
        .sp-btn:disabled { opacity: 0.5; cursor: not-allowed; }

        /* ─── Composer ─── */
        .composer-wrap { padding: 14px 28px 18px; border-top: 1px solid var(--rule); background: var(--paper); }
        .composer { max-width: 700px; margin: 0 auto; display: flex; align-items: flex-end; gap: 8px; padding: 10px 10px 10px 12px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-lg); }
        .composer:focus-within { border-color: var(--terracotta); box-shadow: 0 0 0 3px var(--terracotta-tint); }
        .composer.is-disabled { opacity: 0.7; }
        .composer-input { flex: 1; min-height: 24px; max-height: 180px; overflow-y: auto; font: inherit; font-size: 14.5px; color: var(--ink-3); outline: none; line-height: 1.5; padding: 2px 4px; }
        .composer-attach, .composer-send { width: 32px; height: 32px; flex: 0 0 32px; display: flex; align-items: center; justify-content: center; background: transparent; border: 0; border-radius: 8px; color: var(--ink-3); cursor: pointer; }
        .composer-attach:hover { background: var(--paper-3); color: var(--ink); }
        .composer-send { background: var(--terracotta); color: #fff; }
        .composer-send:disabled { opacity: 0.5; }
        .composer-hint { max-width: 700px; margin: 8px auto 0; display: flex; justify-content: space-between; font-size: 11px; color: var(--ink-3); }
        .composer-phase { display: inline-flex; align-items: center; gap: 6px; }
        .composer-phase .phase-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--terracotta); }

        /* ─── Phase divider ─── */
        .phase-div { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 14px; padding: 6px 0; }
        .phase-line { height: 1px; background: var(--rule); }
        .phase-pill { display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px; background: var(--paper-2); border: 1px solid var(--rule); border-radius: 100px; font-size: 11.5px; color: var(--ink-2); }
        .phase-from { color: var(--ink-3); }
        .phase-to { color: var(--terracotta); font-weight: 500; }

        /* ─── New simulation screen ─── */
        .new-sim-mark { margin-bottom: 16px; }
        .new-sim-title { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 6px; color: var(--ink); }
        .new-sim-sub { font-size: 14px; color: var(--ink-3); line-height: 1.55; margin: 0 0 28px; max-width: 44ch; }
        .new-sim-field { margin-bottom: 22px; }
        .new-sim-label { display: block; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; margin-bottom: 8px; }
        .new-sim-input { width: 100%; padding: 10px 14px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-md); font: inherit; font-size: 14px; color: var(--ink); outline: none; transition: border-color .12s, box-shadow .12s; }
        .new-sim-input:focus { border-color: var(--terracotta); box-shadow: 0 0 0 3px var(--terracotta-tint); }
        .new-sim-input::placeholder { color: var(--ink-4); }
        .new-sim-levels { display: flex; flex-direction: column; gap: 6px; }
        .new-sim-level { display: flex; flex-direction: column; gap: 2px; padding: 12px 16px; background: var(--card); border: 1px solid var(--rule); border-radius: var(--r-md); cursor: pointer; text-align: left; font: inherit; transition: border-color .12s, background .12s; }
        .new-sim-level:hover { border-color: var(--ink-4); background: var(--paper); }
        .new-sim-level.is-active { border-color: var(--terracotta); background: var(--terracotta-tint); }
        .new-sim-level-name { font-size: 14px; font-weight: 500; color: var(--ink); }
        .new-sim-level-desc { font-size: 12.5px; color: var(--ink-3); }
        .new-sim-level.is-active .new-sim-level-name { color: var(--terracotta); }
        .new-sim-start { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; background: var(--terracotta); color: #fff; border: 0; border-radius: var(--r-md); font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; margin-top: 6px; transition: opacity .12s; }
        .new-sim-start:disabled { opacity: 0.4; cursor: not-allowed; }
        .new-sim-start:hover:not(:disabled) { opacity: 0.9; }

        /* ─── Nav bar ─── */
        .nav-bar { display: flex; gap: 2px; padding: 6px 8px; background: var(--paper-2); border-bottom: 1px solid var(--rule); overflow-x: auto; flex-shrink: 0; scrollbar-width: none; }
        .nav-bar::-webkit-scrollbar { display: none; }
        .nav-tab { padding: 6px 12px; border: none; background: transparent; border-radius: 6px; font: inherit; font-size: 12.5px; color: var(--ink-3); cursor: pointer; white-space: nowrap; display: flex; align-items: center; gap: 5px; }
        .nav-tab:hover { background: var(--paper-3); color: var(--ink); }
        .nav-tab.active { background: var(--card); color: var(--ink); font-weight: 500; box-shadow: var(--shadow-sm); }

      `}</style>

      <div className={darkMode ? "theme-dark" : ""} style={{ display:"flex", flexDirection:"column", height:"100vh", width:"100vw", overflow:"hidden" }}>
        {/* Navigation — design preview only */}
        <div className="nav-bar">
          {VIEWS.map(v => (
            <button key={v.id} className={`nav-tab ${view === v.id ? "active" : ""}`} onClick={() => setView(v.id)}>
              <span>{v.icon}</span> {v.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          {view === "new" && <ViewNewSim sidebarProps={sidebarProps}/>}
          {view === "chat" && <ViewChat sidebarProps={sidebarProps}/>}
          {view === "spec" && <ViewSpecSplit sidebarProps={sidebarProps}/>}
          {view === "phase" && <ViewPhase sidebarProps={sidebarProps}/>}
          {view === "workspace" && <ViewWorkspace sidebarProps={sidebarProps}/>}
          {view === "shelf" && <ViewShelfVariants sidebarProps={sidebarProps}/>}
          {view === "trace" && <ViewTrace sidebarProps={sidebarProps}/>}
          {view === "timeline" && <ViewTimeline sidebarProps={sidebarProps}/>}
        </div>
      </div>
    </>
  );
}
