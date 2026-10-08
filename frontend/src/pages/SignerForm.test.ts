import { describe, expect, it } from "vitest";
import { groupInputs } from "./SignerAssignmentDetailPage";

const f = (id: string, over: Record<string, unknown> = {}) => ({
  id, kind: "TEXT", label: "Texte", required: true, group_key: null, page: 1, ...over,
});

describe("groupInputs", () => {
  it("asks once for fields that share a key, on every document page", () => {
    const groups = groupInputs([
      f("a", { label: "Société", group_key: "societe", page: 1 }),
      f("b", { label: "Société", group_key: "societe", page: 2 }),
      f("c", { label: "Fonction" }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ label: "Société", ids: ["a", "b"] });
    expect(groups[1]).toMatchObject({ label: "Fonction", ids: ["c"] });
  });

  it("is required as soon as one field of the group is", () => {
    const groups = groupInputs([
      f("a", { group_key: "k", required: false }),
      f("b", { group_key: "k", required: true }),
    ]);
    expect(groups[0].required).toBe(true);
  });

  it("keeps independent fields independent even if they look alike", () => {
    expect(groupInputs([f("a"), f("b")])).toHaveLength(2);
  });
});
