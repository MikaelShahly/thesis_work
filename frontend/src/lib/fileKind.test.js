import { describe, it, expect } from "vitest";
import { isFigureFile } from "./fileKind.js";

describe("isFigureFile", () => {
  it("treats browser-renderable image types as figures", () => {
    for (const type of ["png", "jpg", "jpeg", "gif", "webp", "svg"]) {
      expect(isFigureFile({ type })).toBe(true);
    }
  });

  it("is case-insensitive on the extension", () => {
    expect(isFigureFile({ type: "PNG" })).toBe(true);
    expect(isFigureFile({ type: "SVG" })).toBe(true);
  });

  it("does not treat TIFF as a figure (browsers can't render it inline)", () => {
    expect(isFigureFile({ type: "tiff" })).toBe(false);
    expect(isFigureFile({ type: "tif" })).toBe(false);
  });

  it("does not treat documents or text as figures", () => {
    for (const type of ["pdf", "html", "md", "txt", ""]) {
      expect(isFigureFile({ type })).toBe(false);
    }
  });

  it("tolerates a missing type or file", () => {
    expect(isFigureFile({})).toBe(false);
    expect(isFigureFile(null)).toBe(false);
    expect(isFigureFile(undefined)).toBe(false);
  });
});
