import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AdminBrandingPage from "./AdminBrandingPage";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), putForm: vi.fn(), del: vi.fn() } };
});

describe("AdminBrandingPage", () => {
  let hasLogo = false;
  beforeEach(() => {
    vi.clearAllMocks();
    hasLogo = false;
    vi.mocked(api.get).mockImplementation(async () => ({
      has_logo: hasLogo,
      logo_sha256: hasLogo ? "a".repeat(64) : null,
    }));
    vi.mocked(api.putForm).mockImplementation(async () => {
      hasLogo = true;
      return {};
    });
    vi.mocked(api.del).mockImplementation(async () => {
      hasLogo = false;
      return {};
    });
  });

  it("shows the LCIT logo until the company sets its own, then offers to go back", async () => {
    render(<AdminBrandingPage />);
    expect(await screen.findByAltText("Logo LCIT par défaut")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revenir au logo LCIT/ })).toBeNull();

    const announced = vi.fn();
    window.addEventListener("lcit-branding-changed", announced);
    const file = new File([new Uint8Array([137, 80, 78, 71])], "logo.png", { type: "image/png" });
    fireEvent.change(screen.getByTestId("logo-input"), { target: { files: [file] } });
    await waitFor(() => expect(api.putForm).toHaveBeenCalledWith("/admin/branding/logo", expect.any(FormData)));
    expect(await screen.findByAltText("Logo actuel")).toHaveAttribute(
      "src",
      `/api/branding/logo?v=${"a".repeat(64)}`,
    );
    // The rest of the page (top-left logo) is told, without a reload.
    expect(announced).toHaveBeenCalled();
    expect(screen.getByText(/dès maintenant en haut à gauche/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Revenir au logo LCIT/ }));
    fireEvent.click(screen.getByRole("button", { name: /Oui, revenir au logo LCIT/ }));
    expect(await screen.findByAltText("Logo LCIT par défaut")).toBeInTheDocument();
    expect(api.del).toHaveBeenCalledWith("/admin/branding/logo");
  });

  it("reports a refused image in words", async () => {
    vi.mocked(api.putForm).mockRejectedValue(
      Object.assign(new Error("Le logo doit être une image PNG ou JPEG"), { status: 422 }),
    );
    render(<AdminBrandingPage />);
    await screen.findByAltText("Logo LCIT par défaut");
    fireEvent.change(screen.getByTestId("logo-input"), {
      target: { files: [new File(["x"], "logo.png", { type: "image/png" })] },
    });
    // A plain Error is not an ApiError: the page still says it failed, never a blank.
    expect(await screen.findByRole("alert")).toHaveTextContent(/échoué|PNG ou JPEG/);
  });
});
