import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UserMenu from "./UserMenu";
import type { Me } from "../api/types";

const user: Me = {
  id: "1",
  email: "alice.martin@lcit-test.local",
  display_name: "Alice Martin",
  roles: ["SIGNER", "ADMIN"],
};

describe("<UserMenu />", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-appearance");
  });

  it("shows who you are and the profiles you hold", () => {
    render(<UserMenu user={user} onSignOut={vi.fn()} />);
    expect(screen.getAllByText("Alice Martin").length).toBeGreaterThan(0);
    expect(screen.getByText("alice.martin@lcit-test.local")).toBeInTheDocument();
    expect(screen.getAllByText("Administrateur").length).toBeGreaterThan(0);
    expect(screen.getByText("Signataire")).toBeInTheDocument();
  });

  it("offers to change the password to a local account (the system one or a created one), not to an SSO one", () => {
    const change = vi.fn();
    const { unmount } = render(<UserMenu user={{ ...user, source: "local" }} onSignOut={vi.fn()} onChangePassword={change} />);
    expect(screen.getByRole("button", { name: /Changer le mot de passe/ })).toBeInTheDocument();
    unmount();
    const builtin = render(<UserMenu user={{ ...user, source: "builtin" }} onSignOut={vi.fn()} onChangePassword={change} />);
    expect(screen.getByRole("button", { name: /Changer le mot de passe/ })).toBeInTheDocument();
    builtin.unmount();
    render(<UserMenu user={{ ...user, source: "sso" }} onSignOut={vi.fn()} onChangePassword={change} />);
    expect(screen.queryByRole("button", { name: /Changer le mot de passe/ })).toBeNull();
  });

  it("names the Signataire profile, the standard one", () => {
    render(<UserMenu user={{ ...user, roles: ["SIGNER"] }} onSignOut={vi.fn()} />);
    expect(screen.getAllByText("Signataire").length).toBeGreaterThan(0);
    expect(screen.queryByText("Préparateur")).toBeNull();
  });

  it("switches to night mode and remembers it", async () => {
    const u = userEvent.setup();
    render(<UserMenu user={user} onSignOut={vi.fn()} />);
    await u.click(screen.getByRole("button", { name: /Nuit/ }));
    expect(document.documentElement).toHaveAttribute("data-appearance", "dark");
    expect(window.localStorage.getItem("lcit-sign.appearance")).toBe("dark");
    await u.click(screen.getByRole("button", { name: /Jour/ }));
    expect(document.documentElement).not.toHaveAttribute("data-appearance");
  });

  it("changes the interface style", async () => {
    const u = userEvent.setup();
    render(<UserMenu user={user} onSignOut={vi.fn()} />);
    await u.click(screen.getByRole("button", { name: /^Azur/ }));
    expect(document.documentElement).toHaveAttribute("data-theme", "azure");
    expect(window.localStorage.getItem("lcit-sign.theme")).toBe("azure");
    await u.click(screen.getByRole("button", { name: /^Bleu/ }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("signs out", async () => {
    const u = userEvent.setup();
    const onSignOut = vi.fn();
    render(<UserMenu user={user} onSignOut={onSignOut} />);
    await u.click(screen.getByRole("button", { name: /Se déconnecter/ }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });
});
