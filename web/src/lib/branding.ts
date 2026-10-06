import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Branding } from "../api/types";

const EVENT = "lcit-branding-changed";

/** Tell every logo on the page that it changed (the administrator just replaced it). */
export function announceBrandingChange(): void {
  window.dispatchEvent(new Event(EVENT));
}

/** The company's logo address, or null when the LCIT one is used. Follows changes made
 *  from the administration page without reloading. Public: the sign-in page uses it too. */
export function useCompanyLogo(): string | null {
  const [logo, setLogo] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const load = () =>
      api
        .get<Branding>("/branding")
        .then((b) => active && setLogo(b.has_logo ? `/api/branding/logo?v=${b.logo_sha256}` : null))
        .catch(() => active && setLogo(null));
    void load();
    window.addEventListener(EVENT, load);
    return () => {
      active = false;
      window.removeEventListener(EVENT, load);
    };
  }, []);
  return logo;
}
