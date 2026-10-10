import { useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { connectorText } from "../i18n/connectors";
import ConnectorFieldControl from "../components/ConnectorFieldControl";
import HelpHint from "../components/HelpHint";
import type { ConnectorField, DirectorySource } from "../api/types";

/** Some settings only matter for some choices of "where does the team name come from":
 *  the attribute when it is read from an attribute, the group filter when it is read from groups. */
function isShown(field: ConnectorField, values: Record<string, string>): boolean {
  const selector = values.team_selector ?? "groups";
  if (field.name === "team_attribute") {
    // LDAP can also read the team from the person's folder: no attribute then.
    return selector === "attribute" || selector === "both";
  }
  if (field.name === "group_filter" || field.name === "member_attribute") {
    return selector === "groups" || selector === "both";
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
  const { t } = useTranslation();
  const spec = source.spec;
  const scope = `dir.${source.source}`;
  const fieldText = (f: ConnectorField, part: "label" | "help" | "example") =>
    connectorText(scope, `fields.${f.name}.${part}`, f[part]);
  const secretText = (part: "label" | "help" | "example") =>
    connectorText(scope, `secret.${part}`, spec?.secret[part] ?? "");
  const specLabel = connectorText(scope, "label", spec?.label ?? "");
  const [fields, setFields] = useState<Record<string, string>>(source.fields);
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  if (!spec) return null;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    // Only the settings that apply to the choices made are sent.
    const sent = Object.fromEntries(
      spec.fields
        .filter((f) => isShown(f, fields))
        .map((f) => [f.name, fields[f.name] ?? (f.kind === "select" ? f.default : "")]),
    );
    try {
      await api.put(`/admin/directory/sources/${source.source}/config`, {
        fields: sent,
        secret: secret || undefined,
        sync_interval_minutes: source.sync_interval_minutes,
      });
      // The secret never stays in the page once it has been sent.
      setSecret("");
      setMessage(t("directory.form.saved"));
      onChanged();
    } catch (err) {
      setMessage(errorText(err, "directory.form.saveFailed"));
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
        <KeyRound size={14} aria-hidden="true" /> {specLabel}{" "}
        {source.configured ? t("directory.form.configured") : t("directory.form.notConfigured")}
      </div>
      {spec.guide && spec.guide.length > 0 && (
        <details className="connector-guide" open={!source.configured}>
          <summary>{t("directory.form.guide", { label: specLabel })}</summary>
          <ol>
            {spec.guide.map((step, index) => (
              <li key={step}>{connectorText(scope, `guide.${index}`, step)}</li>
            ))}
          </ol>
        </details>
      )}
      {spec.fields
        .filter((f) => isShown(f, fields))
        .map((f) => (
          <div key={f.name} className="field">
            <span className="label-line">
              <label htmlFor={`${source.source}-${f.name}`}>{fieldText(f, "label")}</label>
              <HelpHint title={fieldText(f, "label")} example={fieldText(f, "example") || undefined}>
                {fieldText(f, "help")}
              </HelpHint>
            </span>
            <ConnectorFieldControl
              id={`${source.source}-${f.name}`}
              scope={scope}
              field={f}
              value={fields[f.name] ?? ""}
              onChange={(value) => setFields({ ...fields, [f.name]: value })}
            />
          </div>
        ))}
      <div className="field">
        <span className="label-line">
          <label htmlFor={`${source.source}-secret`}>{secretText("label")}</label>
          <HelpHint title={secretText("label")} example={secretText("example") || undefined}>
            {secretText("help")}
          </HelpHint>
        </span>
        <ConnectorFieldControl
          id={`${source.source}-secret`}
          scope={scope}
          field={spec.secret}
          value={secret}
          onChange={setSecret}
          secret
          stored={source.configured}
        />
      </div>
      <div className="form-row">
        <button className="button button--primary" type="submit">
          {t("common.save")}
        </button>
        {source.configured && (
          <button className="button" type="button" onClick={remove}>
            <Trash2 size={14} aria-hidden="true" /> {t("common.delete")}
          </button>
        )}
      </div>
      {message && <p role="status">{message}</p>}
    </form>
  );
}
