import { useState } from "react";
import ConfirmDialog from "./ConfirmDialog.jsx";
import ContextMenu from "./ContextMenu.jsx";
import { isEmbeddableDoc } from "../lib/fileKind.js";
import {
  BrandMark,
  FolderIcon,
  ParaviewIcon,
  PlusIcon,
  ChevronRightIcon,
  ChevronLeftIcon,
  TreeChevronIcon,
  SunIcon,
  MoonIcon,
  TrashIcon,
} from "./icons.jsx";

// Files with this extension get the "Load into ParaView" right-click
// menu. Match-by-suffix because the file tree carries `.type` only as
// the trailing extension lowercased; a `.foam` marker file is the
// universal OpenFOAM entry point.
function isFoamFile(file) {
  return file?.type === "foam" || file?.name?.toLowerCase().endsWith(".foam");
}

// Blessed subfolders — the backend pre-creates these at project
// creation, so they always appear in this fixed order at the top of
// the tree. Mirrors PROJECT_SUBFOLDERS in src/api/routes.py — keep in
// sync. Any *additional* top-level folder the agent or user creates
// (scratch dirs, log artefacts, etc.) is surfaced by the backend's
// /files endpoint and rendered below the blessed ones, sorted
// alphabetically, with the neutral folder colour.
const BLESSED_SUBFOLDERS = ["Specification", "Cases", "Reports", "Geometry"];

// Order the keys of a projectFiles response: blessed first (in their
// canonical order), then whatever else the backend returned sorted
// alphabetically.
function orderedSubfolderNames(projectFiles) {
  if (!projectFiles) return [];
  const present = new Set(Object.keys(projectFiles));
  const blessed = BLESSED_SUBFOLDERS.filter((s) => present.has(s));
  const extras = [...present]
    .filter((s) => !BLESSED_SUBFOLDERS.includes(s))
    .sort((a, b) => a.localeCompare(b));
  return [...blessed, ...extras];
}

// Phase ramp for subfolder folder-icon color, matched to the project-level
// PHASE_COLOR ramp below. Geometry uses the indigo slot — distinct from
// the workflow-phase colors (Spec/Cases/Reports) since it represents
// user input rather than an agent-driven phase output.
const SUBFOLDER_COLOR = {
  Specification: "#B8553C",
  Cases: "var(--ochre)",
  Reports: "var(--sage)",
  Geometry: "var(--indigo)",
};

// Group a flat file list into a nested tree.
// Files have paths like "Cases/baseline/system/controlDict"; the leading
// segment is the top-level subfolder ("Cases") which the caller has already
// keyed on, so we descend by `path.split("/").slice(1)`.
//
// Returned shape: { dirs: { name -> subnode }, files: [...] }
function buildTree(files) {
  const root = { dirs: {}, files: [] };
  for (const f of files) {
    const parts = f.path.split("/").filter(Boolean);
    const inner = parts.slice(1);
    if (inner.length === 0) {
      root.files.push(f);
      continue;
    }
    let node = root;
    for (let i = 0; i < inner.length - 1; i++) {
      const seg = inner[i];
      if (!node.dirs[seg]) node.dirs[seg] = { dirs: {}, files: [] };
      node = node.dirs[seg];
    }
    node.files.push(f);
  }
  return root;
}

// Renders one tree level: nested folder rows first, then files.
// `dirPath` is the full path used as the expansion key (e.g. "Case/system");
// `topSubfolder` is the outermost subfolder name ("Case") and is forwarded
// as `file.subfolder` in select callbacks for parity with the original API.
function TreeLevel({
  node,
  dirPath,
  topSubfolder,
  selectedFilePath,
  onSelectFile,
  onContextFile,
  newFilePaths,
  expandedSubfolders,
  onToggleSubfolder,
}) {
  const dirEntries = Object.entries(node.dirs).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  const fileEntries = [...node.files].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
  return (
    <>
      {dirEntries.map(([dirName, subnode]) => {
        const childPath = `${dirPath}/${dirName}`;
        const isExpanded = !!expandedSubfolders?.[childPath];
        return (
          <div key={childPath} className="sb-sub sb-sub-nested">
            <button
              className="sb-sub-row"
              onClick={() => onToggleSubfolder?.(childPath)}
            >
              <span className="sb-chev"><TreeChevronIcon expanded={isExpanded} /></span>
              <span className="sb-sub-icon" style={{ color: "var(--ink-3)" }}>
                <FolderIcon size={11} />
              </span>
              <span className="sb-sub-name">{dirName}</span>
            </button>
            {isExpanded && (
              <div className="sb-files sb-files-nested">
                <TreeLevel
                  node={subnode}
                  dirPath={childPath}
                  topSubfolder={topSubfolder}
                  selectedFilePath={selectedFilePath}
                  onSelectFile={onSelectFile}
                  onContextFile={onContextFile}
                  newFilePaths={newFilePaths}
                  expandedSubfolders={expandedSubfolders}
                  onToggleSubfolder={onToggleSubfolder}
                />
              </div>
            )}
          </div>
        );
      })}
      {fileEntries.map((f) => (
        <FileRow
          key={f.path}
          file={f}
          isActive={selectedFilePath === f.path}
          isNew={newFilePaths?.has(f.path) ?? false}
          onClick={() => onSelectFile?.({ ...f, subfolder: topSubfolder })}
          onContextMenu={
            onContextFile && isFoamFile(f)
              ? (e) => onContextFile(e, { ...f, subfolder: topSubfolder })
              : undefined
          }
        />
      ))}
    </>
  );
}

function SubfolderRow({
  name,
  files,
  expanded,
  onToggle,
  selectedFilePath,
  onSelectFile,
  onContextFile,
  newFilePaths,
  expandedSubfolders,
  onToggleSubfolder,
}) {
  const tree = buildTree(files);
  const hasContent =
    tree.files.length > 0 || Object.keys(tree.dirs).length > 0;
  return (
    <div className="sb-sub">
      <button className="sb-sub-row" onClick={onToggle}>
        <span className="sb-chev"><TreeChevronIcon expanded={expanded} /></span>
        <span className="sb-sub-icon" style={{ color: SUBFOLDER_COLOR[name] ?? "var(--ink-3)" }}>
          <FolderIcon size={12} />
        </span>
        <span className="sb-sub-name">{name}</span>
      </button>
      {expanded && hasContent && (
        <div className="sb-files">
          <TreeLevel
            node={tree}
            dirPath={name}
            topSubfolder={name}
            selectedFilePath={selectedFilePath}
            onSelectFile={onSelectFile}
            onContextFile={onContextFile}
            newFilePaths={newFilePaths}
            expandedSubfolders={expandedSubfolders}
            onToggleSubfolder={onToggleSubfolder}
          />
        </div>
      )}
    </div>
  );
}

function FileRow({ file, isActive, isNew, onClick, onContextMenu }) {
  const isMono = file.type !== "md";
  return (
    <button
      className={`sb-file ${isActive ? "is-active" : ""} ${isMono ? "is-mono" : ""}`}
      onClick={onClick}
      onContextMenu={onContextMenu}
    >
      <span className="sb-file-name">{file.name}</span>
      {isNew && !isActive && (
        <span className="sb-file-new" title="New since last viewed" />
      )}
    </button>
  );
}

// Map the backend's short phase_display label to a stable color.
// These are phase signals, NOT accent swatches — the Spec color is
// hardcoded (not --terracotta) so it stays put when the user picks
// a different accent. Values: terracotta primary, --ochre, --sage,
// --ink-3 — all independent of the accent CSS vars.
const PHASE_COLOR = {
  Spec: "#B8553C",
  Case: "var(--ochre)",
  Meshing: "var(--ochre)",
  Running: "var(--ochre)",
  Post: "var(--sage)",
  Done: "var(--ink-3)",
};

function relativeTime(iso) {
  if (!iso) return "";
  // SQLite CURRENT_TIMESTAMP returns "YYYY-MM-DD HH:MM:SS" in UTC
  // without a trailing Z. Normalise both shapes to a Date.
  const normalised = iso.includes("T") ? iso : iso.replace(" ", "T") + "Z";
  const t = new Date(normalised).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t);
  const sec = diff / 1000;
  if (sec < 60) return "just now";
  const min = sec / 60;
  if (min < 60) return `${Math.floor(min)}m`;
  const hr = min / 60;
  if (hr < 24) return `${Math.floor(hr)}h`;
  const day = hr / 24;
  if (day < 2) return "yesterday";
  if (day < 7) return `${Math.floor(day)}d`;
  const wk = day / 7;
  if (wk < 5) return `${Math.floor(wk)}w`;
  return `${Math.floor(wk / 4)}mo`;
}

export default function Sidebar({
  projects,
  activeProjectId,
  onSelectProject,
  onNewSimulation,
  onDeleteProject,
  theme,
  onToggleTheme,
  accent,
  onAccent,
  accents,
  collapsed,
  onSetCollapsed,
  // ── Project file tree (only shown under the active project) ────
  projectFiles,
  expandedSubfolders,
  onToggleSubfolder,
  selectedFilePath,
  onSelectFile,
  newFilePaths,
  // Right-click "Load into ParaView" handler (passed `path` only).
  // Optional — if absent, .foam rows behave like any other file.
  onLoadFoamIntoParaview,
}) {
  // The sidebar owns its collapsed state unless a parent forces it
  // (e.g., review mode auto-collapses it). Controlled/uncontrolled hybrid.
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const isCollapsed = collapsed !== undefined ? collapsed : internalCollapsed;
  const setCollapsed = onSetCollapsed ?? setInternalCollapsed;

  // Context menu + confirm dialog state for right-click-to-delete.
  // Both hold { id, name } for the target project (plus x/y on the menu).
  const [contextMenu, setContextMenu] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  // Separate context menu for right-clicks on files. Holds
  // { path, name, type, x, y }. Items shown depend on the file type:
  // .foam → "Load into ParaView"; .html/.pdf → "Open in new tab".
  const [fileContextMenu, setFileContextMenu] = useState(null);

  function handleProjectContextMenu(e, project) {
    if (!onDeleteProject) return;
    e.preventDefault();
    setContextMenu({
      id: project.id,
      name: project.name,
      x: e.clientX,
      y: e.clientY,
    });
  }

  function handleFileContextMenu(e, file) {
    // Only files with an actionable item get a menu: .foam (Load into
    // ParaView, when the handler is wired) or .html/.pdf (Open in new
    // tab). Anything else falls through to the native menu.
    const canFoam = isFoamFile(file) && !!onLoadFoamIntoParaview;
    const canOpenTab = isEmbeddableDoc(file);
    if (!canFoam && !canOpenTab) return;
    e.preventDefault();
    e.stopPropagation();
    setFileContextMenu({
      path: file.path,
      name: file.name,
      type: file.type,
      x: e.clientX,
      y: e.clientY,
    });
  }

  if (isCollapsed) {
    return (
      <aside className="sb is-collapsed">
        <button className="sb-rail" onClick={() => setCollapsed(false)} title="Open sidebar">
          <div className="sb-rail-brand"><BrandMark size={22} /></div>
          <div className="sb-rail-icons">
            <div className="sb-rail-btn" title="New simulation"><PlusIcon /></div>
            <div className="sb-rail-btn" title="Projects"><FolderIcon /></div>
          </div>
          <div className="sb-rail-chev"><ChevronRightIcon /></div>
        </button>
      </aside>
    );
  }

  return (
    <aside className="sb">
      <div className="sb-head">
        <div className="sb-brand">
          <BrandMark size={22} />
          <div>
            <div className="sb-brand-name">AgenticCFD</div>
            <div className="sb-brand-sub">local · v0.3</div>
          </div>
        </div>
        <button className="sb-toggle" onClick={() => setCollapsed(true)} title="Collapse">
          <ChevronLeftIcon />
        </button>
      </div>

      <button className="sb-new" onClick={onNewSimulation}>
        <PlusIcon /> New simulation
      </button>

      <div className="sb-section scroll-hidden">
        <div className="sb-section-label">Projects</div>
        {projects.length === 0 ? (
          <div className="sb-section-empty">No projects yet.</div>
        ) : (
          projects.map((p) => {
            const isActive = p.id === activeProjectId;
            return (
              <div key={p.id}>
                <button
                  className={`sb-proj ${isActive ? "is-active" : ""}`}
                  onClick={() => onSelectProject?.(p.id)}
                  onContextMenu={(e) => handleProjectContextMenu(e, p)}
                >
                  <div
                    className="sb-proj-icon"
                    style={{ color: PHASE_COLOR[p.phase_display] ?? "var(--ink-3)" }}
                  >
                    <FolderIcon />
                  </div>
                  <div className="sb-proj-body">
                    <div className="sb-proj-name">{p.name}</div>
                    <div className="sb-proj-meta">
                      <span>{p.phase_display}</span>
                      <span className="dot-sep">·</span>
                      <span>{relativeTime(p.updated_at)}</span>
                    </div>
                  </div>
                </button>
                {isActive && projectFiles && (
                  <div className="sb-tree">
                    {orderedSubfolderNames(projectFiles).map((sub) => (
                      <SubfolderRow
                        key={sub}
                        name={sub}
                        files={projectFiles[sub] ?? []}
                        expanded={!!expandedSubfolders?.[sub]}
                        onToggle={() => onToggleSubfolder?.(sub)}
                        selectedFilePath={selectedFilePath}
                        onSelectFile={onSelectFile}
                        onContextFile={handleFileContextMenu}
                        newFilePaths={newFilePaths}
                        expandedSubfolders={expandedSubfolders}
                        onToggleSubfolder={onToggleSubfolder}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="sb-foot">
        <div className="sb-setting">
          <div className="sb-setting-label">Theme</div>
          <button className="sb-theme-toggle" onClick={onToggleTheme}>
            {theme === "dark" ? (
              <><SunIcon /><span>Light</span></>
            ) : (
              <><MoonIcon /><span>Dark</span></>
            )}
          </button>
        </div>

        <div className="sb-setting">
          <div className="sb-setting-label">Accent</div>
          <div className="sb-accent-row">
            {Object.entries(accents).map(([key, palette]) => (
              <button
                key={key}
                className={`sb-accent-dot ${accent === key ? "is-active" : ""}`}
                style={{ background: palette.primary }}
                onClick={() => onAccent?.(key)}
                title={key}
              />
            ))}
          </div>
        </div>
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
        >
          <button
            className="context-menu-item is-danger"
            onClick={() => {
              setConfirmDelete({ id: contextMenu.id, name: contextMenu.name });
              setContextMenu(null);
            }}
          >
            <TrashIcon />
            <span>Delete</span>
          </button>
        </ContextMenu>
      )}

      {fileContextMenu && (
        <ContextMenu
          x={fileContextMenu.x}
          y={fileContextMenu.y}
          onClose={() => setFileContextMenu(null)}
        >
          {isFoamFile(fileContextMenu) && onLoadFoamIntoParaview && (
            <button
              className="context-menu-item"
              onClick={() => {
                const path = fileContextMenu.path;
                setFileContextMenu(null);
                onLoadFoamIntoParaview?.(path);
              }}
            >
              <ParaviewIcon size={13} />
              <span>Load into ParaView</span>
            </button>
          )}
          {isEmbeddableDoc(fileContextMenu) && (
            <button
              className="context-menu-item"
              onClick={() => {
                const path = fileContextMenu.path;
                setFileContextMenu(null);
                window.open(
                  `/api/projects/${activeProjectId}/file/raw?path=${encodeURIComponent(
                    path,
                  )}`,
                  "_blank",
                  "noopener,noreferrer",
                );
              }}
            >
              <span>Open in new tab</span>
            </button>
          )}
        </ContextMenu>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete "${confirmDelete.name}"?`}
          message="This cannot be undone."
          confirmLabel="Delete"
          cancelLabel="Cancel"
          danger
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => {
            const id = confirmDelete.id;
            setConfirmDelete(null);
            onDeleteProject?.(id);
          }}
        />
      )}
    </aside>
  );
}
