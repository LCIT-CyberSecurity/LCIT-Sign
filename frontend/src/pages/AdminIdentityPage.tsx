import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import AdminDirectoryPage from "./AdminDirectoryPage";
import AdminLoginPage from "./AdminLoginPage";

/** Identités & accès: two different questions on one page. "Connexion" is how people
 *  authenticate (one SSO provider + the local form); "Annuaire" is where users and groups come
 *  from (one directory). Setting one never changes the other. */
export default function AdminIdentityPage() {
  const { t } = useTranslation();
  return (
    <div className="stack">
      <div>
        <h1 className="page-title" style={{ marginBottom: 6 }}>
          <ShieldCheck size={22} aria-hidden="true" /> {t("identityPage.title")}
        </h1>
        <p className="page-subtitle">
          {t("identityPage.subtitle")}
        </p>
      </div>
      <AdminLoginPage />
      <AdminDirectoryPage />
    </div>
  );
}
