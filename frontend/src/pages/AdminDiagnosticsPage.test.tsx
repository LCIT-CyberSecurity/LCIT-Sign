import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AdminDiagnosticsPage from "./AdminDiagnosticsPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { get: vi.fn() } }));

const report = {
  status: "ERROR",
  checked_at: "2026-10-05T12:00:00Z",
  checks: [
    { name: "database", status: "OK", detail: "SELECT 1" },
    { name: "oidc", status: "ERROR", detail: "discovery endpoint unreachable" },
    { name: "worker", status: "DISABLED", detail: "background worker is disabled" },
  ],
};

describe("AdminDiagnosticsPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(report);
  });

  it("shows each component with its status and detail", async () => {
    render(<AdminDiagnosticsPage />);
    expect(await screen.findByTestId("check-database")).toHaveTextContent("PostgreSQL");
    expect(screen.getByTestId("check-oidc")).toHaveTextContent("SSO (OIDC)");
    expect(screen.getByText("discovery endpoint unreachable")).toBeInTheDocument();
    expect(screen.getByText("DISABLED")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/admin/diagnostics");
  });
});
