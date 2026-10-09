import { ShieldCheck } from "lucide-react";
import AdminDirectoryPage from "./AdminDirectoryPage";
import AdminLoginPage from "./AdminLoginPage";

/** Identités & accès: two different questions on one page. "Connexion" is how people
 *  authenticate (one SSO provider + the local form); "Annuaire" is where users and groups come
 *  from (one directory). Setting one never changes the other. */
export default function AdminIdentityPage() {
  return (
    <div className="stack">
      <div>
        <h1 className="page-title" style={{ marginBottom: 6 }}>
          <ShieldCheck size={22} aria-hidden="true" /> Identités &amp; accès
        </h1>
        <p className="page-subtitle">
          Toute personne qui s&apos;authentifie peut entrer dans LCIT Sign ; ce sont ses rôles qui décident de ce
          qu&apos;elle y fait. Même quand Microsoft Entra sert aux deux, ce sont deux réglages distincts.
        </p>
      </div>
      <AdminLoginPage />
      <AdminDirectoryPage />
    </div>
  );
}
