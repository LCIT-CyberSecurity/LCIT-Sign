import { useState } from "react";
import { KeyRound, Trash2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import HelpHint from "../components/HelpHint";
import type { DirectorySource } from "../api/types";

interface Help {
  text: string;
  example: string;
}

interface Spec {
  title: string;
  fields: { key: string; label: string; help: Help }[];
  secretLabel: string;
  secretHelp: Help;
  secretMultiline: boolean;
}

const SPECS: Record<string, Spec> = {
  entra: {
    title: "Microsoft Entra ID",
    fields: [
      {
        key: "tenant_id",
        label: "ID du tenant",
        help: {
          text: "L'identifiant de votre annuaire Microsoft 365 (le « locataire »). Dans le centre d'administration Entra : Vue d'ensemble → ID de locataire.",
          example: "1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d",
        },
      },
      {
        key: "client_id",
        label: "ID de l'application (client)",
        help: {
          text: "L'identifiant de l'application « LCIT Sign » que vous avez inscrite dans Entra : Inscriptions d'applications → votre application → ID de l'application (client).",
          example: "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b",
        },
      },
    ],
    secretLabel: "Secret client",
    secretHelp: {
      text: "Le mot de passe de l'application (pas d'une personne). Il n'est affiché qu'une seule fois, à sa création dans Entra : Certificats et secrets → Nouveau secret client → copiez la Valeur. Il est chiffré dès l'enregistrement et n'est plus jamais réaffiché.",
      example: "abC8Q~xYzTn3kLw0pQe5vRsU9dFgHjKlMnOpQr",
    },
    secretMultiline: false,
  },
  google: {
    title: "Google Workspace",
    fields: [
      {
        key: "admin_email",
        label: "E-mail de l'administrateur à usurper",
        help: {
          text: "L'adresse d'un administrateur Google Workspace au nom duquel le compte de service lit l'annuaire (délégation à l'échelle du domaine). Lecture seule : rien n'est modifié.",
          example: "admin@votre-domaine.fr",
        },
      },
    ],
    secretLabel: "Clé du compte de service (JSON)",
    secretHelp: {
      text: "Le fichier de clé JSON du compte de service créé dans Google Cloud (IAM → Comptes de service → Clés → Ajouter une clé). Collez tout son contenu. Il est chiffré dès l'enregistrement.",
      example: '{ "type": "service_account", "client_email": "lcit-sign@projet.iam.gserviceaccount.com", … }',
    },
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
        <div key={f.key} className="field">
          <span className="label-line">
            <label htmlFor={`${source.source}-${f.key}`}>{f.label}</label>
            <HelpHint title={f.label} example={f.help.example}>
              {f.help.text}
            </HelpHint>
          </span>
          <input
            id={`${source.source}-${f.key}`}
            value={fields[f.key] ?? ""}
            onChange={(e) => setFields({ ...fields, [f.key]: e.target.value })}
            required
          />
        </div>
      ))}
      <div className="field">
        <span className="label-line">
          <label htmlFor={`${source.source}-secret`}>{spec.secretLabel}</label>
          <HelpHint title={spec.secretLabel} example={spec.secretHelp.example}>
            {spec.secretHelp.text}
          </HelpHint>
        </span>
        {spec.secretMultiline ? (
          <textarea
            id={`${source.source}-secret`}
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
            id={`${source.source}-secret`}
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={source.configured ? "•••• enregistré — laisser vide pour le conserver" : ""}
            required={!source.configured}
            autoComplete="new-password"
          />
        )}
      </div>
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
