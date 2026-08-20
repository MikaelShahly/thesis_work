// Tests for the ParaView client + fall-through orchestration in
// `paraview.js`. The plan calls for a "mocked fetch harness" — that's
// exactly what we drive here: each `fetchFn` records its call list
// and returns a synthetic Response so the lib's HTTP/error mapping
// can be exercised without a backend.
//
// Two flows are mandated by phase-2 §2.3:
//   1. Right-click "Load into ParaView" path: 409 from /load falls
//      through to /launch with the same .foam.
//   2. Toolbar button: 409 from /launch surfaces the backend's
//      message verbatim so the App can render it as a toast.

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  launchParaview,
  loadIntoParaview,
  loadOrLaunchParaview,
} from "./paraview.js";

// Build a minimal Response stand-in that satisfies the bits the lib
// reads (`ok`, `status`, `json()`). Keeps tests free of node-fetch /
// undici imports.
function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function makeFetchSequence(responses) {
  // Sequential mock: each call pops the next response off the list.
  // The recorded `calls` array preserves call order so tests can
  // assert URLs and bodies in sequence.
  const calls = [];
  const fetchFn = vi.fn(async (url, init) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (!next) throw new Error(`fetch called more times than mocked: ${url}`);
    return next;
  });
  return { fetchFn, calls };
}

describe("launchParaview", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  it("returns kind: 'launched' on 200", async () => {
    const { fetchFn, calls } = makeFetchSequence([
      jsonResponse(200, { status: "launched", pid: 4242, port: 8765 }),
    ]);
    const result = await launchParaview("proj-1", { fetchFn });
    expect(result.kind).toBe("launched");
    expect(result.record.pid).toBe(4242);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/projects/proj-1/paraview/launch");
    expect(JSON.parse(calls[0].init.body)).toEqual({});
  });

  it("includes foam_file in the body when provided", async () => {
    const { fetchFn, calls } = makeFetchSequence([
      jsonResponse(200, { status: "launched", pid: 1 }),
    ]);
    await launchParaview("proj-1", { foamFile: "Cases/baseline/case.foam", fetchFn });
    expect(JSON.parse(calls[0].init.body)).toEqual({ foam_file: "Cases/baseline/case.foam" });
  });

  it("returns kind: 'conflict' with the backend's message on 409", async () => {
    // Phase 2.1: "the backend message renders as a toast" — the lib
    // forwards `detail.message` and `detail.running_for_project`
    // verbatim so the caller can build the toast without parsing.
    const { fetchFn } = makeFetchSequence([
      jsonResponse(409, {
        detail: {
          message: "ParaView is already open for 'Cylinder Flow'. Close that window and try again.",
          running_for_project: "Cylinder Flow",
        },
      }),
    ]);
    const result = await launchParaview("proj-2", { fetchFn });
    expect(result.kind).toBe("conflict");
    expect(result.message).toContain("Cylinder Flow");
    expect(result.runningForProject).toBe("Cylinder Flow");
  });

  it("throws on unexpected non-200/409 (5xx)", async () => {
    const { fetchFn } = makeFetchSequence([
      jsonResponse(500, { detail: "spawn failed" }),
    ]);
    await expect(launchParaview("proj-1", { fetchFn })).rejects.toThrow(/spawn failed/);
  });
});

describe("loadIntoParaview", () => {
  it("returns kind: 'loaded' on 200", async () => {
    const { fetchFn } = makeFetchSequence([
      jsonResponse(200, { status: "loaded", path: "/abs/Cases/baseline/case.foam" }),
    ]);
    const result = await loadIntoParaview("proj-1", "Cases/baseline/case.foam", { fetchFn });
    expect(result.kind).toBe("loaded");
    expect(result.path).toBe("/abs/Cases/baseline/case.foam");
  });

  it("returns kind: 'no_instance' on 409 (not running)", async () => {
    const { fetchFn } = makeFetchSequence([
      jsonResponse(409, { detail: "ParaView is not open." }),
    ]);
    const result = await loadIntoParaview("proj-1", "Cases/baseline/case.foam", { fetchFn });
    expect(result.kind).toBe("no_instance");
    expect(result.message).toMatch(/not open/);
  });
});

describe("loadOrLaunchParaview (right-click fall-through)", () => {
  it("loads into the running instance when /load returns 200", async () => {
    const { fetchFn, calls } = makeFetchSequence([
      jsonResponse(200, { status: "loaded", path: "/abs/Cases/baseline/case.foam" }),
    ]);
    const result = await loadOrLaunchParaview("proj-1", "Cases/baseline/case.foam", { fetchFn });
    expect(result.kind).toBe("loaded");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/projects/proj-1/paraview/load");
  });

  it("falls through to /launch with the same .foam on /load 409", async () => {
    // Phase 2.2 path: the optimistic /load returns 409 (no instance);
    // the lib MUST follow with /launch carrying the same foam_file
    // as the initial case. This is the contract the right-click
    // menu in Sidebar.jsx relies on.
    const { fetchFn, calls } = makeFetchSequence([
      jsonResponse(409, { detail: "ParaView is not open." }),
      jsonResponse(200, { status: "launched", pid: 9001 }),
    ]);
    const result = await loadOrLaunchParaview(
      "proj-1",
      "Cases/baseline/case.foam",
      { fetchFn },
    );
    expect(result.kind).toBe("launched");
    expect(result.record.pid).toBe(9001);
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toBe("/api/projects/proj-1/paraview/load");
    expect(calls[1].url).toBe("/api/projects/proj-1/paraview/launch");
    // The foam file MUST be threaded through to /launch, not dropped.
    expect(JSON.parse(calls[1].init.body)).toEqual({
      foam_file: "Cases/baseline/case.foam",
    });
  });

  it("propagates kind: 'conflict' when the fall-through /launch hits another project's instance", async () => {
    // Phase 2.2 outer 409: instance running for a *different*
    // project — surfaces backend message for the toast.
    const { fetchFn } = makeFetchSequence([
      jsonResponse(409, { detail: "ParaView is not open." }),
      jsonResponse(409, {
        detail: {
          message: "ParaView is already open for 'Backstep'. Close that window and try again.",
          running_for_project: "Backstep",
        },
      }),
    ]);
    const result = await loadOrLaunchParaview(
      "proj-1",
      "Cases/baseline/case.foam",
      { fetchFn },
    );
    expect(result.kind).toBe("conflict");
    expect(result.runningForProject).toBe("Backstep");
  });
});
