import { useCallback, useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import ChatColumn from "./components/ChatColumn.jsx";
import SpecPanel from "./components/SpecPanel.jsx";
import FilePanel from "./components/FilePanel.jsx";
import Lightbox from "./components/Lightbox.jsx";
import { isFigureFile, isEmbeddableDoc } from "./lib/fileKind.js";
import SpecResizeHandle from "./components/SpecResizeHandle.jsx";
import { useAgentStream } from "./hooks/useAgentStream.js";
import { useToastQueue } from "./hooks/useToastQueue.js";
import { launchParaview, loadOrLaunchParaview } from "./lib/paraview.js";

const ACCENTS = {
  terracotta: { primary: "#B8553C", primary2: "#D97A5F", tint: "#F3DFD4" },
  sage: { primary: "#6E8A6A", primary2: "#8CA686", tint: "#DDE5D3" },
  indigo: { primary: "#4F5B92", primary2: "#6A79B3", tint: "#DCE0EE" },
  ochre: { primary: "#B4862E", primary2: "#D1A34F", tint: "#F1E4C0" },
};

// Spec-panel resize persistence.
const SPEC_WIDTH_KEY = "specPanelWidth";
const SPEC_WIDTH_DEFAULT = 380;
const SPEC_WIDTH_MIN = 260;
const SPEC_WIDTH_MAX = 820;

// Sidebar resize persistence — lets deep, nested file trees be read
// without clipping. Same load/persist shape as the spec panel.
const SIDEBAR_WIDTH_KEY = "sidebarWidth";
const SIDEBAR_WIDTH_DEFAULT = 240;
const SIDEBAR_WIDTH_MIN = 200;
const SIDEBAR_WIDTH_MAX = 520;

function clampedLocalNumber(key, fallback, min, max) {
  const raw = typeof window !== "undefined" ? window.localStorage.getItem(key) : null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

function loadSpecWidth() {
  return clampedLocalNumber(SPEC_WIDTH_KEY, SPEC_WIDTH_DEFAULT, SPEC_WIDTH_MIN, SPEC_WIDTH_MAX);
}

function loadSidebarWidth() {
  return clampedLocalNumber(
    SIDEBAR_WIDTH_KEY,
    SIDEBAR_WIDTH_DEFAULT,
    SIDEBAR_WIDTH_MIN,
    SIDEBAR_WIDTH_MAX,
  );
}

async function fetchJson(input, init) {
  const res = await fetch(input, init);
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
  return res.json();
}

export default function App() {
  // ── UI state ─────────────────────────────────────────────────
  const [theme, setTheme] = useState("light");
  const [accent, setAccent] = useState("indigo");

  // ── Data state ───────────────────────────────────────────────
  const [projects, setProjects] = useState([]);
  const [currentProjectId, setCurrentProjectId] = useState(null);
  const [currentProject, setCurrentProject] = useState(null);

  // ── Layout state ─────────────────────────────────────────────
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth);
  const [specPanelWidth, setSpecPanelWidth] = useState(loadSpecWidth);

  // ── Project file tree (sidebar tree + click-to-view) ─────────
  // projectFiles is keyed by subfolder name; null means "not loaded yet
  // for this project". expandedSubfolders + selectedFile reset on every
  // project switch (per design).
  const [projectFiles, setProjectFiles] = useState(null);
  const [expandedSubfolders, setExpandedSubfolders] = useState({});
  const [selectedFile, setSelectedFile] = useState(null);
  // A figure opened in the modal lightbox: { name, path }. Independent
  // of selectedFile — figures don't mount the side FilePanel.
  const [lightboxFile, setLightboxFile] = useState(null);

  // Per-tab "new since seen" set, namespaced by projectId so two
  // projects with the same path don't share dots. Lost on page reload.
  const [newFiles, setNewFiles] = useState(new Map());

  // Toast stack (top-left of the chat column). Cap of 4 visible,
  // overflow queues. Reset on project switch.
  // Destructure so the stable useCallback refs can be used in deps
  // arrays without the visible-array changes re-firing other effects.
  const {
    visible: toastNotifs,
    enqueue: enqueueToast,
    dismiss: dismissToast,
    reset: resetToasts,
  } = useToastQueue();

  const refreshProjects = useCallback(async () => {
    try {
      setProjects(await fetchJson("/api/projects"));
    } catch (err) {
      console.error("GET /api/projects failed:", err);
    }
  }, []);

  const refreshProjectFiles = useCallback(async (projectId) => {
    try {
      const tree = await fetchJson(`/api/projects/${projectId}/files`);
      setProjectFiles(tree);
    } catch (err) {
      console.error(`GET /api/projects/${projectId}/files failed:`, err);
    }
  }, []);

  const refetchCurrentProject = useCallback(async () => {
    if (!currentProjectId) return;
    try {
      setCurrentProject(await fetchJson(`/api/projects/${currentProjectId}`));
      await Promise.all([refreshProjects(), refreshProjectFiles(currentProjectId)]);
    } catch (err) {
      console.error(`GET /api/projects/${currentProjectId} failed:`, err);
    }
  }, [currentProjectId, refreshProjects, refreshProjectFiles]);

  // ── Agent stream (owns messages + review state for current project)
  const handleFileWritten = useCallback(
    (payload) => {
      // payload: { name, path, type, subfolder }
      if (!currentProjectId) return;

      // Coalesced Bash summary — a shell command (mkdir/cp during the
      // improver phase) touched many files at once. Surface ONE FYI
      // toast instead of one per file. The files reach the sidebar tree
      // via the silent /files refetch (handleBashCompleted), so there's
      // no tree merge or is-new dot here.
      if (payload.summary) {
        enqueueToast({
          kind: "message",
          title: `${payload.count} ${payload.count === 1 ? "file" : "files"} added`,
          body: payload.subfolders?.join(" · "),
          projectId: currentProjectId,
        });
        return;
      }

      // 1. Toast — surfaces the new file in the chat-column gutter.
      enqueueToast({ ...payload, projectId: currentProjectId });

      // 2. Mark the file new for the dot in the sidebar tree.
      setNewFiles((prev) => {
        const next = new Map(prev);
        const set = new Set(next.get(currentProjectId) ?? []);
        set.add(payload.path);
        next.set(currentProjectId, set);
        return next;
      });

      // 3. Merge into the local file tree so the sidebar shows it
      //    immediately without re-fetching /files.
      setProjectFiles((prev) => {
        if (!prev) return prev;
        const sub = payload.subfolder;
        const subFiles = prev[sub] ?? [];
        if (subFiles.some((f) => f.path === payload.path)) {
          return prev; // Edit on an existing file — tree unchanged.
        }
        const merged = [
          ...subFiles,
          { name: payload.name, path: payload.path, type: payload.type },
        ];
        merged.sort((a, b) => a.path.localeCompare(b.path));
        return { ...prev, [sub]: merged };
      });
    },
    [currentProjectId, enqueueToast],
  );

  // After every Bash tool call completes, refetch /files so anything
  // the shell did (mv/cp/rm/mkdir, plus mesher outputs like blockMesh
  // populating constant/polyMesh/) lands in the sidebar tree. Quiet —
  // no toast, no "is-new" dot. The hook debounces parallel Bash bursts
  // into one refetch.
  const handleBashCompleted = useCallback(() => {
    if (!currentProjectId) return;
    refreshProjectFiles(currentProjectId);
  }, [currentProjectId, refreshProjectFiles]);

  const stream = useAgentStream(currentProjectId, {
    onProjectChanged: refetchCurrentProject,
    onFileWritten: handleFileWritten,
    onBashCompleted: handleBashCompleted,
  });

  // Derived: are we in review mode? (spec draft exists AND project
  // hasn't transitioned to the next phase yet.) Used for the has-spec
  // grid class, SpecPanel mount, and sidebar auto-collapse.
  const inReview =
    !!stream.specDraft && currentProject?.phase === "simulation_spec";

  // Fetch the sidebar list once on mount.
  useEffect(() => {
    refreshProjects();
  }, [refreshProjects]);

  // Fetch project detail + file tree when the selection changes.
  // Tree state (expanded/selected) is reset on switch — sidebar always
  // returns to "all subfolders collapsed, no file selected" per design.
  // Toast queue is also wiped (toasts are project-local).
  useEffect(() => {
    if (!currentProjectId) {
      setCurrentProject(null);
      setProjectFiles(null);
      setExpandedSubfolders({});
      setSelectedFile(null);
      setLightboxFile(null);
      resetToasts();
      return;
    }
    setExpandedSubfolders({});
    setSelectedFile(null);
    setLightboxFile(null);
    setProjectFiles(null);
    resetToasts();
    // Tell the backend this is now the active project. This single token
    // drives ParaView single-tenancy (only the active project may reach
    // the live bridge) and session lifecycle (switching away lets the
    // backend reap the previous project's idle worker). Fire-and-forget.
    fetchJson(`/api/projects/${currentProjectId}/activate`, { method: "POST" })
      .catch((err) => console.error("activate failed:", err));
    let cancelled = false;
    Promise.all([
      fetchJson(`/api/projects/${currentProjectId}`),
      fetchJson(`/api/projects/${currentProjectId}/files`),
    ])
      .then(([proj, tree]) => {
        if (cancelled) return;
        setCurrentProject(proj);
        setProjectFiles(tree);
      })
      .catch((err) => {
        if (!cancelled) console.error(`Project load for ${currentProjectId} failed:`, err);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, resetToasts]);

  // Apply the accent to CSS custom properties.
  useEffect(() => {
    const p = ACCENTS[accent];
    const root = document.documentElement.style;
    root.setProperty("--terracotta", p.primary);
    root.setProperty("--terracotta-2", p.primary2);
    root.setProperty("--terracotta-tint", p.tint);
  }, [accent]);

  // Persist spec-panel width on change.
  useEffect(() => {
    try {
      window.localStorage.setItem(SPEC_WIDTH_KEY, String(specPanelWidth));
    } catch {
      /* quota / private mode — ignore */
    }
  }, [specPanelWidth]);

  // Persist sidebar width on change.
  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
    } catch {
      /* quota / private mode — ignore */
    }
  }, [sidebarWidth]);

  const createProject = useCallback(
    async (body) => {
      const created = await fetchJson("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      // Set currentProject optimistically BEFORE refreshing the sidebar.
      // Otherwise, between refreshProjects resolving and the project-detail
      // fetch resolving, the landing is still mounted and sees its own
      // new project in the sidebar list — flashing the "already exists"
      // warning for one render. The detail useEffect will still fire and
      // overwrite this with the server's version (same data, no visible
      // change). See history shape in src/api/routes.py::get_project.
      setCurrentProject({ ...created, spec_draft: null, history: [] });
      setCurrentProjectId(created.id);
      await refreshProjects();
      return created;
    },
    [refreshProjects],
  );

  const handleToggleSubfolder = useCallback((sub) => {
    setExpandedSubfolders((prev) => ({ ...prev, [sub]: !prev[sub] }));
  }, []);

  const handleSelectFile = useCallback(
    async (file) => {
      if (!currentProjectId) return;
      // Clicking a file clears its is-new dot.
      setNewFiles((prev) => {
        const set = prev.get(currentProjectId);
        if (!set || !set.has(file.path)) return prev;
        const next = new Map(prev);
        const updated = new Set(set);
        updated.delete(file.path);
        next.set(currentProjectId, updated);
        return next;
      });
      // Figures open in the modal lightbox via the raw-bytes endpoint —
      // they're not text, so they skip the JSON /file roundtrip and the
      // side FilePanel entirely.
      if (isFigureFile(file)) {
        setLightboxFile({ name: file.name, path: file.path });
        return;
      }
      // HTML/PDF deliverables render in the FilePanel via an <iframe>
      // pointed at /file/raw — no JSON text roundtrip (a PDF wouldn't
      // utf-8-decode, and we don't want raw HTML source). FilePanel
      // keys off `is_doc` to mount the iframe.
      if (isEmbeddableDoc(file)) {
        setSelectedFile({ ...file, is_doc: true, content: null });
        return;
      }
      // Optimistically mark selection so the sidebar row highlights
      // before the content roundtrips back.
      setSelectedFile({ ...file, content: null });
      try {
        const detail = await fetchJson(
          `/api/projects/${currentProjectId}/file?path=${encodeURIComponent(file.path)}`,
        );
        setSelectedFile({ ...detail, subfolder: file.subfolder });
      } catch (err) {
        console.error(`GET file ${file.path} failed:`, err);
        setSelectedFile(null);
      }
    },
    [currentProjectId],
  );

  // Live-tail the open text file. Once the initial content has loaded
  // (is_binary === false), poll `/file?offset=<bytes we have>` every 2s
  // and append the new bytes — so a growing log (a running solver/mesh
  // job written to log.* in the case dir) streams into the FilePanel
  // without re-opening it. Skips docs (iframe), binaries, and figures
  // (lightbox). Idles off once the file stops growing (~12s); a 404 —
  // the agent cleaned the file up — stops it. Pure read, never writes:
  // the agent's view of its own files is untouched.
  useEffect(() => {
    const path = selectedFile?.path;
    if (!currentProjectId || !path || selectedFile?.is_binary !== false) return;
    let cancelled = false;
    let offset = selectedFile.size ?? 0;
    let idle = 0;
    let timer = null;
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    async function poll() {
      let res;
      try {
        res = await fetch(
          `/api/projects/${currentProjectId}/file?path=${encodeURIComponent(path)}&offset=${offset}`,
        );
      } catch {
        return; // transient — retry next tick
      }
      if (cancelled) return;
      if (res.status === 404) {
        stop(); // file removed (agent cleanup) — leave last content shown
        return;
      }
      if (!res.ok) return;
      const d = await res.json();
      if (cancelled) return;
      if (d.is_binary) {
        stop(); // never tail binaries
        return;
      }
      if (d.truncated) {
        offset = d.size;
        idle = 0;
        setSelectedFile((prev) =>
          prev?.path === path ? { ...prev, content: d.content ?? "", size: d.size } : prev,
        );
      } else if (d.content) {
        offset = d.size;
        idle = 0;
        setSelectedFile((prev) =>
          prev?.path === path
            ? { ...prev, content: (prev.content ?? "") + d.content, size: d.size }
            : prev,
        );
      } else if (++idle >= 6) {
        stop(); // static for ~12s → stop polling (re-open to resume)
      }
    }
    timer = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      stop();
    };
  }, [currentProjectId, selectedFile?.path, selectedFile?.is_binary]);

  // Toast click → open the file + expand its subfolder + dismiss toast.
  // Message-kind toasts (ParaView 409s, etc.) just dismiss; there is
  // no associated file to navigate to.
  const handleOpenToast = useCallback(
    (notification) => {
      const { payload, id } = notification;
      if ((payload.kind ?? "file") !== "file") {
        dismissToast(id);
        return;
      }
      setExpandedSubfolders((prev) => ({ ...prev, [payload.subfolder]: true }));
      handleSelectFile({
        name: payload.name,
        path: payload.path,
        type: payload.type,
        subfolder: payload.subfolder,
      });
      dismissToast(id);
    },
    [handleSelectFile, dismissToast],
  );

  // ── ParaView launch / load orchestration ─────────────────────
  // Two flows, one shared shape: we POST, then either do nothing
  // (the user sees the ParaView window appear) or surface a toast
  // with the backend's exact message. Network/5xx errors fall to a
  // generic toast so the UI doesn't go silent.
  // Heads-up toast for the auto-cleanup path: backend detected an
  // untracked ParaView still running (typically a backend-restart
  // orphan), SIGKILL'd it, and is spawning a fresh instance.
  const maybeOrphanToast = useCallback(
    (result) => {
      if (result?.kind === "launched" && result.record?.cleaned_orphan) {
        enqueueToast({
          kind: "message",
          icon: "paraview",
          title: "Cleaned up untracked ParaView",
          body: "An untracked ParaView instance was running in the background — closing it and starting a new instance.",
        });
      }
    },
    [enqueueToast],
  );

  const handleLaunchParaview = useCallback(async () => {
    if (!currentProjectId) return;
    try {
      const result = await launchParaview(currentProjectId);
      if (result.kind === "conflict") {
        enqueueToast({
          kind: "message",
          icon: "paraview",
          title: "ParaView is already open",
          body: result.message,
        });
        return;
      }
      maybeOrphanToast(result);
    } catch (err) {
      console.error("POST /paraview/launch failed:", err);
      enqueueToast({
        kind: "message",
        icon: "paraview",
        title: "Could not launch ParaView",
        body: String(err.message || err),
      });
    }
  }, [currentProjectId, enqueueToast, maybeOrphanToast]);

  const handleLoadFoamIntoParaview = useCallback(
    async (foamPath) => {
      if (!currentProjectId || !foamPath) return;
      try {
        const result = await loadOrLaunchParaview(currentProjectId, foamPath);
        if (result.kind === "conflict") {
          enqueueToast({
            kind: "message",
            icon: "paraview",
            title: "ParaView is already open",
            body: result.message,
          });
          return;
        }
        // The fall-through path (load → 409 → launch) returns a
        // `launched` result if the launch step ran. cleaned_orphan
        // would have been surfaced there.
        maybeOrphanToast(result);
      } catch (err) {
        console.error("POST /paraview/load (or fall-through) failed:", err);
        enqueueToast({
          kind: "message",
          icon: "paraview",
          title: "Could not load into ParaView",
          body: String(err.message || err),
        });
      }
    },
    [currentProjectId, enqueueToast, maybeOrphanToast],
  );

  // ── Geometry upload ──────────────────────────────────────────
  // Returns the file record on success; throws on failure so the
  // Composer can render the error inline. On success we route the
  // record through `handleFileWritten` so user uploads land in the
  // sidebar tree, fire a toast, and pick up the "is-new" dot the
  // exact same way agent-written files do — the user shouldn't
  // perceive a difference. We also refetch /files authoritatively
  // so a collision-renamed name (cylinder_1.stl) overrides the
  // optimistic merge.
  const handleUploadGeometry = useCallback(
    async (file) => {
      if (!currentProjectId) {
        throw new Error("No project selected");
      }
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `/api/projects/${currentProjectId}/geometry`,
        { method: "POST", body: form },
      );
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (typeof body?.detail === "string") detail = body.detail;
          else if (body?.detail?.message) detail = body.detail.message;
        } catch {
          /* non-JSON response */
        }
        throw new Error(detail);
      }
      const record = await res.json();
      // Same shape `handleFileWritten` expects from the agent's
      // PostToolUse hook ({ name, path, type, subfolder }) — that
      // function owns the toast + is-new dot + tree merge in one
      // place, so calling it keeps the upload UX in lock-step with
      // agent-driven writes.
      handleFileWritten({
        name: record.name,
        path: record.path,
        type: record.type,
        subfolder: record.subfolder ?? "Geometry",
      });
      // Re-fetch authoritatively so collision-renamed files
      // (cylinder_1.stl, etc.) reflect even if the optimistic merge
      // already inserted the same path under a different name.
      refreshProjectFiles(currentProjectId);
      return record;
    },
    [currentProjectId, handleFileWritten, refreshProjectFiles],
  );

  const deleteProject = useCallback(
    async (projectId) => {
      let result;
      try {
        result = await fetchJson(`/api/projects/${projectId}`, { method: "DELETE" });
      } catch (err) {
        console.error(`DELETE /api/projects/${projectId} failed:`, err);
        return;
      }
      // If the deleted one was selected, drop back to the landing.
      setCurrentProjectId((cur) => (cur === projectId ? null : cur));
      await refreshProjects();
      // The deleted project owned the live ParaView window, which now points
      // at removed files. We don't kill it for the user — just ask them to
      // close it. Deferred a tick so the toast lands after the switch-to-
      // landing reset (the resetToasts in the currentProjectId effect).
      if (result?.paraview_attached) {
        setTimeout(
          () =>
            enqueueToast({
              kind: "message",
              icon: "paraview",
              title: "Close the ParaView window",
              body: "It was attached to the project you just deleted.",
            }),
          0,
        );
      }
    },
    [refreshProjects, enqueueToast],
  );

  // Selection wins over review mode — if the user clicks a file in the
  // tree, show that file. Otherwise fall back to the live spec_draft
  // panel during review. Only one right panel is mounted at a time.
  const showFilePanel = !!selectedFile;
  const showSpecPanel = !showFilePanel && inReview;
  const rightPanelMounted = showFilePanel || showSpecPanel;

  // Grid columns: [sidebar] [sidebar handle?] 1fr [spec handle + spec?].
  // The sidebar column is driven explicitly so the drag handle can resize
  // it; collapsed pins it to the 48px rail and hides its handle.
  const sidebarCol = sidebarCollapsed ? "48px" : `${sidebarWidth}px`;
  const sidebarHandleCol = sidebarCollapsed ? "" : " 8px";
  const specCols = rightPanelMounted ? ` 8px ${specPanelWidth}px` : "";
  const appStyle = {
    gridTemplateColumns: `${sidebarCol}${sidebarHandleCol} 1fr${specCols}`,
  };

  return (
    <div className={`theme-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <div className={`app ${rightPanelMounted ? "has-spec" : ""}`} style={appStyle}>
        <Sidebar
          projects={projects}
          activeProjectId={currentProjectId}
          onSelectProject={setCurrentProjectId}
          onNewSimulation={() => setCurrentProjectId(null)}
          onDeleteProject={deleteProject}
          theme={theme}
          onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          accent={accent}
          onAccent={setAccent}
          accents={ACCENTS}
          collapsed={sidebarCollapsed}
          onSetCollapsed={setSidebarCollapsed}
          projectFiles={projectFiles}
          expandedSubfolders={expandedSubfolders}
          onToggleSubfolder={handleToggleSubfolder}
          selectedFilePath={selectedFile?.path}
          onSelectFile={handleSelectFile}
          newFilePaths={newFiles.get(currentProjectId)}
          onLoadFoamIntoParaview={handleLoadFoamIntoParaview}
        />
        {!sidebarCollapsed && (
          <SpecResizeHandle
            width={sidebarWidth}
            setWidth={setSidebarWidth}
            min={SIDEBAR_WIDTH_MIN}
            max={SIDEBAR_WIDTH_MAX}
            side="left"
          />
        )}
        <ChatColumn
          project={currentProject}
          stream={stream}
          inReview={inReview}
          onCreateProject={createProject}
          projects={projects}
          toastNotifications={toastNotifs}
          onOpenToast={handleOpenToast}
          onLaunchParaview={handleLaunchParaview}
          onUploadGeometry={handleUploadGeometry}
        />
        {rightPanelMounted && (
          <SpecResizeHandle
            width={specPanelWidth}
            setWidth={setSpecPanelWidth}
            min={SPEC_WIDTH_MIN}
            max={SPEC_WIDTH_MAX}
          />
        )}
        {showFilePanel && (
          <FilePanel
            projectId={currentProjectId}
            projectName={currentProject?.name}
            file={selectedFile}
            onClose={() => setSelectedFile(null)}
            onLoadFoamIntoParaview={handleLoadFoamIntoParaview}
          />
        )}
        {showSpecPanel && (
          <SpecPanel
            title={currentProject?.name}
            markdown={stream.specDraft}
            streaming={stream.streaming}
            // Only surface approve on the panel once the user has
            // dismissed the AcceptPanel ("Ask a question →"). While
            // AcceptPanel is mounted, Yes lives there instead — we
            // don't want two approve buttons on screen at once.
            onApprove={stream.acceptMode === null ? stream.approveSpec : undefined}
          />
        )}
      </div>
      {lightboxFile && (
        <Lightbox
          projectId={currentProjectId}
          file={lightboxFile}
          onClose={() => setLightboxFile(null)}
        />
      )}
    </div>
  );
}
