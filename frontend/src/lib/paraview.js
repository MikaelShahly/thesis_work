// ParaView API client + the launch/load fall-through logic.
//
// Two endpoints, three flows; the orchestration lives here so the UI
// pieces (toolbar button, right-click menu) stay tiny and testable
// against a mocked `fetch` without React in the loop.
//
// Phase-2 callers:
//   - launchParaview(projectId)            — toolbar "Open ParaView"
//   - loadIntoParaview(projectId, foam)    — right-click "Load into ParaView"
//                                              on a .foam file
//
// Both resolve to a discriminated result the caller turns into a
// toast or a no-op. We deliberately do NOT throw on 409 — the
// "instance already running for project X" case is part of the
// expected vocabulary, not an error. Network failures and unexpected
// HTTP codes do throw.

/**
 * Read FastAPI's HTTPException detail from a non-OK Response.
 *
 * The shape varies:
 * - For ParaviewAlreadyRunningError we return `detail: { message,
 *   running_for_project }`.
 * - For other 4xx/5xx the detail is just a string.
 *
 * Returns `{ message: string, runningForProject: string | null }`.
 * Falls back to a generic message if the body isn't JSON.
 */
async function readDetail(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    return { message: `HTTP ${response.status}`, runningForProject: null };
  }
  const detail = body?.detail;
  if (typeof detail === "string") {
    return { message: detail, runningForProject: null };
  }
  if (detail && typeof detail === "object") {
    return {
      message: detail.message ?? `HTTP ${response.status}`,
      runningForProject: detail.running_for_project ?? null,
    };
  }
  return { message: `HTTP ${response.status}`, runningForProject: null };
}

/**
 * POST /api/projects/{id}/paraview/launch.
 *
 * Resolves to one of:
 *   { kind: 'launched', record }         // 200
 *   { kind: 'conflict', message, runningForProject } // 409
 *
 * Throws on non-200/409 (network failure, 5xx, etc.) so the caller
 * surfaces an unexpected-error toast distinct from the conflict path.
 */
export async function launchParaview(projectId, { foamFile = null, fetchFn = fetch } = {}) {
  const body = foamFile ? { foam_file: foamFile } : {};
  const res = await fetchFn(`/api/projects/${projectId}/paraview/launch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    return { kind: "launched", record: await res.json() };
  }
  if (res.status === 409) {
    const { message, runningForProject } = await readDetail(res);
    return { kind: "conflict", message, runningForProject };
  }
  const { message } = await readDetail(res);
  throw new Error(`launch failed: ${message}`);
}

/**
 * POST /api/projects/{id}/paraview/load with the foam file path.
 *
 * Resolves to:
 *   { kind: 'loaded', path }       // 200, file loaded into running bridge
 *   { kind: 'no_instance', message } // 409, no ParaView running
 *
 * Throws on other non-OK responses.
 */
export async function loadIntoParaview(projectId, foamFile, { fetchFn = fetch } = {}) {
  const res = await fetchFn(`/api/projects/${projectId}/paraview/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ foam_file: foamFile }),
  });
  if (res.ok) {
    const body = await res.json();
    return { kind: "loaded", path: body.path };
  }
  if (res.status === 409) {
    const { message } = await readDetail(res);
    return { kind: "no_instance", message };
  }
  const { message } = await readDetail(res);
  throw new Error(`load failed: ${message}`);
}

/**
 * Phase-2 right-click flow: try to load into the running instance;
 * if there isn't one, fall through to launch with this `.foam` as
 * the initial case.
 *
 * Resolves to:
 *   { kind: 'loaded', path }                                  // /load 200
 *   { kind: 'launched', record }                              // /launch 200
 *     (the launch was the fall-through after /load 409)
 *   { kind: 'conflict', message, runningForProject }          // /launch 409
 *     (an instance is running for a different project)
 *
 * Throws on unexpected errors (5xx, network).
 */
export async function loadOrLaunchParaview(projectId, foamFile, { fetchFn = fetch } = {}) {
  const loadResult = await loadIntoParaview(projectId, foamFile, { fetchFn });
  if (loadResult.kind === "loaded") return loadResult;

  // /load returned 409 — no instance running. Optimistic fall-through
  // to /launch with the foam as the initial case.
  return await launchParaview(projectId, { foamFile, fetchFn });
}
