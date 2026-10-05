import { useState } from "react";
import { KeyRound, Trash2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { DirectorySource } from "../api/types";

interface Spec {
  title: string;
  fields: { key: string; label: string }[];
  secretLabel: string;
  secretMultiline: boolean;
}

const SPECS: Record<string, Spec> = {
  entra: {
    title: "Microsoft Entra ID",
    fields: [
      { key: "tenant_id", label: "ID du tenant" },
      { key: "client_id", label: "ID de l'application (client)" },
    ],
    secretLabel: "Secret client",
    secretMultiline: false,
  },
  google: {
    title: "Google Workspace",
    fields: [{ key: "admin_email", label: "E-mail de l'administrateur à usurper" }],
    secretLabel: "Clé du compte de service (JSON)",
    secretMultiline: true,
  },
};

export default function DirectoryConnectorForm({
  source,
  onChanged,
}: {
  source: DirectorySource;
  onChanged: () => void;
}) {
  const spec = SPECS[source.source];
  const [fields, setFields] = useState<Record<string, string>>(source.fields);
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  if (!spec) return null;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    try {
      await api.put(`/admin/directory/sources/${source.source}/config`, {
        fields,
        secret: secret || undefined,
        sync_interval_minutes: source.sync_interval_minutes,
      });
      // The secret never stays in the page once it has been sent.
      setSecret("");
      setMessage("Configuration enregistrée (secret chiffré).");
      onChanged();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Échec de l'enregistrement.");
    }
  };

  const remove = async () => {
    await api.del(`/admin/directory/sources/${source.source}/config`);
    setFields({});
    setSecret("");
    setMessage(null);
    onChanged();
  };

  return (
    <form className="card form" onSubmit={save} autoComplete="off">
      <div className="card-title">
        <KeyRound size={14} aria-hidden="true" /> {spec.title}{" "}
        {source.configured ? "(configuré)" : "(non configuré)"}
      </div>
      {spec.fields.map((f) => (
        <label key={f.key}>
          {f.label}
          <input
            value={fields[f.key] ?? ""}
            onChange={(e) => setFields({ ...fields, [f.key]: e.target.value })}
            required
          />
        </label>
      ))}
      <label>
        {spec.secretLabel}
        {spec.secretMultiline ? (
          <textarea
            rows={4}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={source.configured ? "•••• enregistré — laisser vide pour le conserver" : ""}
            required={!source.configured}
            autoComplete="off"
            spellCheck={false}
          />
        ) : (
          <input
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={source.configured ? "•••• enregistré — laisser vide pour le conserver" : ""}
            required={!source.configured}
            autoComplete="new-password"
          />
        )}
      </label>
      <div className="form-row">
        <button className="button button--primary" type="submit">
          Enregistrer
        </button>
        {source.configured && (
          <button className="button" type="button" onClick={remove}>
            <Trash2 size={14} aria-hidden="true" /> Supprimer
          </button>
        )}
      </div>
      {message && <p role="status">{message}</p>}
    </form>
  );
}
