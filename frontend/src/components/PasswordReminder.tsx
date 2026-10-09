import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import ChangePasswordDialog from "./ChangePasswordDialog";

export const REMINDER_KEY = "lcit-sign.password-reminder-shown";

function alreadyShownThisSession(): boolean {
  try {
    return window.sessionStorage.getItem(REMINDER_KEY) === "1";
  } catch {
    return false;
  }
}

function markShown(): void {
  try {
    window.sessionStorage.setItem(REMINDER_KEY, "1");
  } catch {
    // Private mode: the banner is still there, the dialog may just reopen.
  }
}

/** While the built-in account still has its initial password: a banner on every
 *  page (always), and the change dialog opens by itself once per sign-in. Signing
 *  out clears the memory (see Shell), so the next sign-in shows it again; a page
 *  reload within the same sign-in does not re-open it. */
export default function PasswordReminder() {
  const { user } = useAuth();
  const [open, setOpen] = useState(() => !alreadyShownThisSession());
  const mustChange = Boolean(user?.must_change_password);
  useEffect(() => {
    if (mustChange) markShown();
  }, [mustChange]);
  if (!mustChange) return null;
  return (
    <>
      <div className="reminder-banner" role="alert" data-testid="password-reminder">
        <ShieldAlert size={16} aria-hidden="true" />
        <span>
          Le mot de passe initial du compte système n&apos;a pas été changé : il est connu de tous.
        </span>
        <button type="button" className="button button--sm button--primary" onClick={() => setOpen(true)}>
          Le changer maintenant
        </button>
      </div>
      {open && <ChangePasswordDialog onClose={() => setOpen(false)} />}
    </>
  );
}
