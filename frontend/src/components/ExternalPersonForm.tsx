import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { UserPlus } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import HelpHint from "./HelpHint";

export interface ExternalPerson {
  id: string;
  email: string;
  display_name: string;
  external: boolean;
  existing?: boolean;
}

/** Add someone from outside the company by e-mail address, so they can be asked to sign. No account
 *  is created anywhere: they sign in with their own and are recognised by this address. */
export default function ExternalPersonForm({
  onCreated,
  onCancel,
}: {
  onCreated: (person: ExternalPerson) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [givenName, setGivenName] = useState("");
  const [familyName, setFamilyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setBusy(true);
    setError(null);
    try {
      const person = await api.post<ExternalPerson>("/campaigns/_meta/externals", {
        email,
        given_name: givenName,
        family_name: familyName,
      });
      onCreated(person);
    } catch (err) {
      setError(errorText(err, "external.addFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    // Not a <form>: it sits inside the page's own forms.
    <div className="card external-form" role="group" aria-label={t("external.groupLabel")}>
      <div className="card-title">
        <UserPlus size={14} aria-hidden="true" /> {t("external.title")}
        <HelpHint title={t("external.helpTitle")} example="jean.client@partenaire.com">
          {t("external.help")}
        </HelpHint>
      </div>
      <div className="form-row">
        <label>
          {t("external.givenName")}
          <input value={givenName} onChange={(e) => setGivenName(e.target.value)} maxLength={120} />
        </label>
        <label>
          {t("external.familyName")}
          <input value={familyName} onChange={(e) => setFamilyName(e.target.value)} maxLength={120} />
        </label>
      </div>
      <label>
        {t("external.email")}
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="jean.client@partenaire.com"
          required
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit(e as unknown as FormEvent);
          }}
        />
      </label>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="row-actions">
        <button type="button" className="button button--primary button--sm" disabled={busy || !email.trim()} onClick={(e) => void submit(e as unknown as FormEvent)}>
          {t("users.add")}
        </button>
        <button type="button" className="button button--ghost button--sm" onClick={onCancel}>
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}
