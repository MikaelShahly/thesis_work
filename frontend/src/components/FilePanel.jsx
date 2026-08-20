import { useEffect, useRef, useState } from "react";
import ContextMenu from "./ContextMenu.jsx";
import DictView from "./DictView.jsx";
import { ParaviewIcon } from "./icons.jsx";
import Markdown from "./Markdown.jsx";

// Subfolders whose files are OpenFOAM dictionaries — DictView's
// tokenizer is generic enough that no per-file logic is needed.
const DICT_SUBFOLDERS = new Set(["Cases"]);

function isFoamFile(file) {
  return file?.type === "foam" || file?.name?.toLowerCase().endsWith(".foam");
}

// Format a byte count for the binary-file placeholder. Single-line
// helper so the renderer dispatch below stays readable.
function formatBytes(n) {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value >= 100 || unit === 0 ? Math.round(value) : value.toFixed(1);
  return `${rounded} ${units[unit]}`;
}

// Right-pane component for browsing a file picked from the sidebar tree.
// Renderer dispatch:
//   `.md`                 → Markdown.jsx
//   Cases/ files          → DictView (regex tokenizer)
//   else                  → plain monospace <pre>
//
// `file` shape: { name, path, type, content, subfolder } — with
// `content === null` while the read roundtrip is in flight.
//
// `.foam` files surface a "Load into ParaView" right-click menu on
// the header (mirrors the sidebar tree's right-click). The header is
// the only stable handle in this panel; right-clicking the body
// would conflict with text-selection menus.
export default function FilePanel({
  projectId,
  projectName,
  file,
  onClose,
  onLoadFoamIntoParaview,
}) {
  const kicker = file?.subfolder
    ? `${projectName ?? "Project"} · ${file.subfolder}`
    : projectName ?? "Project";

  const [headerMenu, setHeaderMenu] = useState(null);
  const canLoadFoam = !!onLoadFoamIntoParaview && isFoamFile(file);

  // Follow-the-tail: when the open file grows (live log streaming in via
  // App's tail loop), keep the view pinned to the bottom — but only if
  // the user is already near the bottom, so scrolling up to read isn't
  // yanked away. Reset per file so opening a fresh file shows its top.
  const bodyRef = useRef(null);
  const prevLenRef = useRef(0);
  const atBottomRef = useRef(true);
  useEffect(() => {
    prevLenRef.current = 0;
    atBottomRef.current = true;
  }, [file?.path]);
  useEffect(() => {
    const el = bodyRef.current;
    const len = file?.content?.length ?? 0;
    const grew = len > prevLenRef.current && prevLenRef.current > 0;
    prevLenRef.current = len;
    if (el && grew && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [file?.content]);
  function handleBodyScroll(e) {
    const el = e.currentTarget;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  function handleHeaderContextMenu(e) {
    if (!canLoadFoam) return;
    e.preventDefault();
    setHeaderMenu({ x: e.clientX, y: e.clientY });
  }

  return (
    <aside className="spec-panel">
      <div className="spec-panel-head" onContextMenu={handleHeaderContextMenu}>
        <div>
          <div className="spec-panel-kicker">{kicker}</div>
          <div className="spec-panel-title">{file?.name ?? ""}</div>
        </div>
        {onClose && (
          <button
            className="spec-panel-close"
            onClick={onClose}
            title="Close file"
            aria-label="Close file"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3 3l6 6M9 3l-6 6" />
            </svg>
          </button>
        )}
      </div>
      <div className="spec-panel-body" ref={bodyRef} onScroll={handleBodyScroll}>
        {/*
          Render-state dispatch:
          - `is_binary === undefined && content === null` → loading
            (App sets `content: null` optimistically before the fetch
            resolves; `is_binary` is only set on the server response).
          - `is_binary === true` → "Binary geometry file · <size>"
            placeholder (geometry uploads in Geometry/, e.g. binary STL).
          - `.md` → Markdown.
          - Cases/ files → DictView.
          - else → plain monospace pre.
        */}
        {file?.is_doc ? (
          // HTML/PDF deliverable: the browser renders it natively from
          // the raw-bytes endpoint. Right-click the sidebar row for
          // "Open in new tab".
          //
          // Sandbox only for HTML — an agent-generated report could
          // carry scripts, so we deny same-origin to keep it from
          // touching the app. PDFs are NOT sandboxed: Chrome renders
          // them via its internal PDF plugin, which a sandboxed frame
          // blocks ("This page has been blocked by Chrome"). A PDF is a
          // passive document from our own same-origin endpoint, so
          // there's nothing to sandbox against.
          <iframe
            className="file-panel-doc"
            title={file?.name ?? "document"}
            src={`/api/projects/${projectId}/file/raw?path=${encodeURIComponent(
              file.path,
            )}`}
            {...(file?.type === "pdf"
              ? {}
              : { sandbox: "allow-scripts allow-popups" })}
          />
        ) : file?.is_binary === undefined && file?.content === null ? (
          <div className="file-panel-loading">Loading…</div>
        ) : file?.is_binary ? (
          <div className="file-panel-binary">
            Binary geometry file · {formatBytes(file.size) || "unknown size"}
          </div>
        ) : file?.type === "md" ? (
          <Markdown source={file.content ?? ""} />
        ) : DICT_SUBFOLDERS.has(file?.subfolder) ? (
          <DictView content={file.content ?? ""} />
        ) : (
          <pre className="file-panel-pre">{file?.content ?? ""}</pre>
        )}
      </div>

      {headerMenu && (
        <ContextMenu
          x={headerMenu.x}
          y={headerMenu.y}
          onClose={() => setHeaderMenu(null)}
        >
          <button
            className="context-menu-item"
            onClick={() => {
              const path = file?.path;
              setHeaderMenu(null);
              if (path) onLoadFoamIntoParaview?.(path);
            }}
          >
            <ParaviewIcon size={13} />
            <span>Load into ParaView</span>
          </button>
        </ContextMenu>
      )}
    </aside>
  );
}
