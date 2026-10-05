import { KIND_BY_ID, type FieldKind } from "./kinds";

/** A rectangle in page fractions: 0..1, origin at the page's top-left. */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const MIN_WIDTH = 0.04;
export const MIN_HEIGHT = 0.02;
const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);

/** Keep an element wholly on its page. */
export function clampRect(r: Rect): Rect {
  const width = clamp(r.width, MIN_WIDTH, 1);
  const height = clamp(r.height, MIN_HEIGHT, 1);
  return {
    width,
    height,
    x: clamp(r.x, 0, 1 - width),
    y: clamp(r.y, 0, 1 - height),
  };
}

export function moveRect(r: Rect, dx: number, dy: number): Rect {
  return clampRect({ ...r, x: r.x + dx, y: r.y + dy });
}

/** Grow or shrink from the bottom-right corner; the top-left stays put. */
export function resizeRect(r: Rect, dw: number, dh: number): Rect {
  const width = clamp(r.width + dw, MIN_WIDTH, 1 - r.x);
  const height = clamp(r.height + dh, MIN_HEIGHT, 1 - r.y);
  return { ...r, width, height };
}

export interface Bounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** A pointer position as a fraction of a page element. */
export function pointToFraction(clientX: number, clientY: number, bounds: Bounds) {
  return {
    x: clamp((clientX - bounds.left) / bounds.width, 0, 1),
    y: clamp((clientY - bounds.top) / bounds.height, 0, 1),
  };
}

/** A new element of `kind`, centred on a point and kept on the page. A box is
 *  sized in proportion to the page so an A4 and a landscape slide both get
 *  something sensible. */
export function placeCentered(kind: FieldKind, point: { x: number; y: number }): Rect {
  const meta = KIND_BY_ID[kind];
  return clampRect({
    width: meta.width,
    height: meta.height,
    x: point.x - meta.width / 2,
    y: point.y - meta.height / 2,
  });
}

/** Round to 4 decimals (0.01 % of a page): stable values on the wire. */
export const tidy = (r: Rect): Rect => ({
  x: Math.round(r.x * 1e4) / 1e4,
  y: Math.round(r.y * 1e4) / 1e4,
  width: Math.round(r.width * 1e4) / 1e4,
  height: Math.round(r.height * 1e4) / 1e4,
});
