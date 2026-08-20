// Composer's message-builder owns the contract between the chip UI
// and what the LLM actually receives. The chip is a visual hint to
// the user; the *string* is what reaches the agent — and the agent's
// prompt is going to teach it to look for "Geometry attached: …" /
// "User uploaded geometry: …" patterns. These tests pin both
// shapes so a refactor can't silently strip the geometry reference
// from the message text and leave the agent guessing what the chip
// referred to.

import { describe, expect, it } from "vitest";
import { buildMessage } from "./Composer.jsx";

describe("Composer buildMessage", () => {
  it("returns the typed text untouched when no chips are attached", () => {
    expect(buildMessage("Use cylinder.stl as the geometry", [])).toBe(
      "Use cylinder.stl as the geometry",
    );
  });

  it("returns an empty string when there is no text and no chips", () => {
    // The composer uses this to gate the send button.
    expect(buildMessage("   ", [])).toBe("");
  });

  it("appends an attachment footer when text + chips coexist", () => {
    const msg = buildMessage("Use this as the geometry.", [
      { name: "cylinder.stl", path: "Geometry/cylinder.stl" },
    ]);
    expect(msg).toBe(
      "Use this as the geometry.\n\n[Geometry attached: cylinder.stl]",
    );
  });

  it("lists multiple chips comma-separated in the footer", () => {
    const msg = buildMessage("Mesh both bodies.", [
      { name: "wing.stl", path: "Geometry/wing.stl" },
      { name: "fuselage.obj", path: "Geometry/fuselage.obj" },
    ]);
    expect(msg).toContain("[Geometry attached: wing.stl, fuselage.obj]");
  });

  it("bare upload (no text) produces a 'User uploaded geometry: …' line", () => {
    // Phase-3 §3.3: a bare upload still sends a message so the
    // agent can acknowledge the file without the user needing to
    // type anything.
    const msg = buildMessage("", [
      { name: "cylinder.stl", path: "Geometry/cylinder.stl" },
    ]);
    expect(msg).toBe("User uploaded geometry: cylinder.stl");
  });

  it("ignores pure whitespace as 'no text'", () => {
    // The submit guard trims; mirror that here so a user who
    // typed-then-deleted ends up in the bare-upload branch, not the
    // text+chip branch with a blank prefix.
    const msg = buildMessage("\n  \t  ", [
      { name: "cylinder.stl", path: "Geometry/cylinder.stl" },
    ]);
    expect(msg).toBe("User uploaded geometry: cylinder.stl");
  });
});
