import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PasswordReminder, { REMINDER_KEY } from "./PasswordReminder";

const auth = vi.hoisted(() => ({ user: null as null | { must_change_password?: boolean } }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: auth.user, refresh: vi.fn() }) }));
vi.mock("../api/client", () => ({ api: { post: vi.fn() }, ApiError: class extends Error {} }));

describe("<PasswordReminder />", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("says nothing to anyone who has no initial password to change", () => {
    auth.user = { must_change_password: false };
    const { container } = render(<PasswordReminder />);
    expect(container).toBeEmptyDOMElement();
  });

  it("nags with a banner and opens the change dialog by itself at sign-in", () => {
    auth.user = { must_change_password: true };
    render(<PasswordReminder />);
    expect(screen.getByTestId("password-reminder")).toHaveTextContent("n'a pas été changé");
    expect(screen.getByRole("dialog", { name: /Changer le mot de passe/ })).toBeInTheDocument();
  });

  it("'Plus tard' closes the dialog but the banner stays", async () => {
    auth.user = { must_change_password: true };
    const user = userEvent.setup();
    render(<PasswordReminder />);
    await user.click(screen.getByRole("button", { name: "Plus tard" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("password-reminder")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Le changer maintenant" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("does not re-open by itself on a reload within the same sign-in, but does after sign-out", () => {
    auth.user = { must_change_password: true };
    const first = render(<PasswordReminder />);
    first.unmount();
    render(<PasswordReminder />); // a reload: same tab session
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("password-reminder")).toBeVisible();

    window.sessionStorage.removeItem(REMINDER_KEY); // what signing out does
    render(<PasswordReminder />);
    expect(screen.getAllByRole("dialog").length).toBeGreaterThan(0);
  });
});
