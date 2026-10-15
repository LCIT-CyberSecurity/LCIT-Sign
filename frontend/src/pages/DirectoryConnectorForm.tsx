import { useState } from "react";
import { KeyRound, Trash2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConnectorFieldControl from "../components/ConnectorFieldControl";
import HelpHint from "../components/HelpHint";
import type {
  ConnectorField,
  DirectoryAttribute,
  DirectoryMappingPreview,
  DirectorySource,
} from "../api/types";

/** Some settings only matter for some choices of "where does the team name come from":
 *  the attribute when it is read from an attribute, the group filter when it is read from groups. */
function isShown(field: ConnectorField, values: Record<string, string>): boolean {
  const selector = values.team_selector ?? "groups";
  if (field.name === "team_attribute") {
    // LDAP can also read the team from the person's folder: no attribute then.
    return selector === "attribute" || selector === "both";
  }
  if (field.name === "custom_team_attribute" || field.name === "custom_team_groups") {
    return selector === "custom_attribute";
  }
  if (field.name === "group_filter" || field.name === "member_attribute") {
    return selector === "groups" || selector === "both" ||
      (selector === "custom_attribute" && values.custom_team_groups === "true");
  }
  return true;
}

/** The form of one directory connector, drawn from the description the server gives of it:
 *  its settings, a help bubble with an example on each, and its one write-only secret. */
export default function DirectoryConnectorForm({
  source,
  onChanged,
}: {
  source: DirectorySource;
  onChanged: () => void;
}) {
  const spec = source.spec;
  const [fields, setFields] = useState<Record<string, string>>(source.fields);
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [attributes, setAttributes] = useState<DirectoryAttribute[] | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [testing, setTesting] = useState(false);
  const [preview, setPreview] = useState<DirectoryMappingPreview | null>(null);
  const [toolError, setToolError] = useState<string | null>(null);

  if (!spec) return null;

  const candidateFields = Object.fromEntries(
    spec.fields.map((field) => [field.name, fields[field.name] ?? field.default]),
  );

  const discover = async () => {
    setDiscovering(true);
    setToolError(null);
    setPreview(null);
    try {
      const result = await api.post<{ attributes: DirectoryAttribute[] }>(
        `/admin/directory/sources/${source.source}/attributes/discover`,
        { fields: candidateFields },
      );
      setAttributes(result.attributes);
      if (result.attributes.length === 0) setToolError("Aucun attribut accessible dans l'échantillon.");
    } catch (err) {
      setToolError(err instanceof ApiError ? err.message : "Échec de la découverte des attributs.");
    } finally {
      setDiscovering(false);
    }
  };

  const testMapping = async () => {
    setTesting(true);
    setToolError(null);
    try {
      const result = await api.post<DirectoryMappingPreview>(
        `/admin/directory/sources/${source.source}/mapping/preview`,
        { fields: candidateFields },
      );
      setPreview(result);
    } catch (err) {
      setToolError(err instanceof ApiError ? err.message : "Échec de la prévisualisation.");
    } finally {
      setTesting(false);
    }
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    // Only the settings that apply to the choices made are sent.
    const sent = Object.fromEntries(
      spec.fields
        .filter((f) => isShown(f, fields) || f.name === "custom_team_attribute" || f.name === "custom_team_groups")
        .map((f) => [f.name, fields[f.name] ?? f.default]),
    );
    try {
      await api.put(`/admin/directory/sources/${source.source}/config`, {
        fields: sent,
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
        <KeyRound size={14} aria-hidden="true" /> {spec.label} {source.configured ? "(configuré)" : "(non configuré)"}
      </div>
      {spec.guide && spec.guide.length > 0 && (
        <details className="connector-guide" open={!source.configured}>
          <summary>Comment préparer {spec.label}, pas à pas</summary>
          <ol>
            {spec.guide.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </details>
      )}
      {spec.fields
        .filter((f) => isShown(f, fields))
        .map((f) => (
          <div key={f.name} className="field">
            <span className="label-line">
              <label htmlFor={`${source.source}-${f.name}`}>{f.label}</label>
              <HelpHint title={f.label} example={f.example || undefined}>
                {f.help}
              </HelpHint>
            </span>
            <ConnectorFieldControl
              id={`${source.source}-${f.name}`}
              field={f.name === "custom_team_attribute"
                ? {
                    ...f,
                    options: [
                      { value: "", label: "Choisissez un attribut découvert" },
                      ...(attributes ?? [])
                        .filter((attribute) => attribute.available)
                        .map((attribute) => ({
                          value: attribute.name,
                          label: `${attribute.label} — ${attribute.name}`,
                        })),
                    ],
                  }
                : f}
              value={fields[f.name] ?? ""}
              onChange={(value) => setFields({ ...fields, [f.name]: value })}
            />
          </div>
        ))}
      {fields.team_selector === "custom_attribute" && (
        <section className="field" aria-label="Découverte des attributs d'équipe">
          <button
            className="button button--secondary button--sm"
            type="button"
            onClick={() => void discover()}
            disabled={!source.configured || discovering}
          >
            {discovering ? "Découverte…" : "Découvrir les attributs"}
          </button>
          {attributes && attributes.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 8 }}>
              <table className="simple-table directory-attributes-table">
                <thead><tr><th>Attribut</th><th>Disponibilité</th><th>Renseigné</th><th>Exemples</th></tr></thead>
                <tbody>
                  {attributes.map((attribute) => (
                    <tr key={attribute.name}>
                      <td>{attribute.label}<br /><code>{attribute.name}</code></td>
                      <td>{attribute.available ? "Accessible" : "Non accessible"}</td>
                      <td>{attribute.populated_count}/{attribute.sample_count} ({Math.round(attribute.population_ratio * 100)} %)</td>
                      <td>{attribute.examples.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {attributes && attributes.length === 0 && <p className="muted small">Aucun attribut découvert.</p>}
          <button
            className="button button--secondary button--sm"
            type="button"
            onClick={() => void testMapping()}
            disabled={!source.configured || testing || !fields.custom_team_attribute}
          >
            {testing ? "Test du mapping…" : "Tester le mapping"}
          </button>
          <p className="muted small">Le test lit un échantillon sans enregistrer ni synchroniser les données.</p>
        </section>
      )}
      {!source.active && (
        <p className="muted small" role="note">
          Enregistrer cette configuration activera ce connecteur et remplacera l'annuaire actuellement utilisé.
        </p>
      )}
      <div className="field">
        <span className="label-line">
          <label htmlFor={`${source.source}-secret`}>{spec.secret.label}</label>
          <HelpHint title={spec.secret.label} example={spec.secret.example || undefined}>
            {spec.secret.help}
          </HelpHint>
        </span>
        <ConnectorFieldControl
          id={`${source.source}-secret`}
          field={spec.secret}
          value={secret}
          onChange={setSecret}
          secret
          stored={source.configured}
        />
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
      {toolError && <p className="error-text" role="alert">{toolError}</p>}
      {preview && (
        <section className="section-panel" aria-label="Résultat du test de mapping">
          <p className="muted small">Résultat sur {preview.sampled_users} utilisateurs échantillonnés</p>
          {preview.active_comparison && (
            <p>Écarts avec l'annuaire actif : {preview.active_comparison.added} ajout(s), {preview.active_comparison.removed} retrait(s).</p>
          )}
          {preview.teams.length === 0 && <p className="muted">Aucune équipe détectée.</p>}
          {preview.teams.map((team) => (
            <details key={team.name}>
              <summary>{team.name} — {team.member_count} membre(s)</summary>
              <ul>{team.members.map((person) => <li key={person.email}>{person.name} — {person.email}</li>)}</ul>
            </details>
          ))}
          <details>
            <summary>Sans équipe — {preview.unassigned_users.length}</summary>
            <ul>{preview.unassigned_users.map((person) => <li key={person.email}>{person.name} — {person.email}</li>)}</ul>
          </details>
          {preview.warnings.map((warning) => <p className="muted small" key={warning}>{warning}</p>)}
        </section>
      )}
    </form>
  );
}
