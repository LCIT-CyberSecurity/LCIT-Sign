import { describe, expect, it } from "vitest";
import {
  MIN_HEIGHT,
  MIN_WIDTH,
  clampRect,
  moveRect,
  placeCentered,
  pointToFraction,
  resizeRect,
  tidy,
} from "./geometry";

const box = { x: 0.2, y: 0.3, width: 0.2, height: 0.05 };

describe("moving an element", () => {
  it("moves by the given fraction", () => {
    expect(moveRect(box, 0.1, -0.1)).toEqual({ ...box, x: 0.30000000000000004, y: 0.19999999999999998 });
  });

  it("can never leave the page", () => {
    expect(moveRect(box, -5, -5)).toMatchObject({ x: 0, y: 0 });
    const far = moveRect(box, 5, 5);
    expect(far.x + far.width).toBeCloseTo(1);
    expect(far.y + far.height).toBeCloseTo(1);
  });
});

describe("resizing an element", () => {
  it("grows from the bottom-right corner and keeps its top-left", () => {
    expect(resizeRect(box, 0.1, 0.05)).toMatchObject({ x: 0.2, y: 0.3, width: 0.30000000000000004 });
  });

  it("stops at the page edge and at a usable minimum", () => {
    const grown = resizeRect(box, 5, 5);
    expect(grown.x + grown.width).toBeCloseTo(1);
    expect(grown.y + grown.height).toBeCloseTo(1);
    const shrunk = resizeRect(box, -5, -5);
    expect(shrunk.width).toBe(MIN_WIDTH);
    expect(shrunk.height).toBe(MIN_HEIGHT);
  });
});

describe("clampRect", () => {
  it("pulls an overflowing element back inside", () => {
    expect(clampRect({ x: 0.9, y: 0.95, width: 0.3, height: 0.1 })).toEqual({
      x: 0.7,
      y: 0.9,
      width: 0.3,
      height: 0.1,
    });
  });
});

describe("pointToFraction", () => {
  it("turns screen pixels into page fractions", () => {
    const bounds = { left: 100, top: 50, width: 400, height: 800 };
    expect(pointToFraction(300, 450, bounds)).toEqual({ x: 0.5, y: 0.5 });
  });

  it("clamps a pointer released outside the page", () => {
    const bounds = { left: 100, top: 50, width: 400, height: 800 };
    expect(pointToFraction(0, 10_000, bounds)).toEqual({ x: 0, y: 1 });
  });
});

describe("placeCentered", () => {
  it("centres a new element on the drop point", () => {
    const r = placeCentered("DATE", { x: 0.5, y: 0.5 });
    expect(r.x + r.width / 2).toBeCloseTo(0.5);
    expect(r.y + r.height / 2).toBeCloseTo(0.5);
  });

  it("keeps an element dropped in a corner on the page", () => {
    const r = placeCentered("SIGNATURE", { x: 1, y: 1 });
    expect(r.x + r.width).toBeLessThanOrEqual(1);
    expect(r.y + r.height).toBeLessThanOrEqual(1);
  });
});

describe("tidy", () => {
  it("rounds to a stable precision for the wire", () => {
    expect(tidy({ x: 0.123456789, y: 0.2, width: 0.30000000000000004, height: 0.05 })).toEqual({
      x: 0.1235,
      y: 0.2,
      width: 0.3,
      height: 0.05,
    });
  });
});
