import type { ConnectorField } from "../api/types";

/** The input for one connector setting, whatever its kind (text, secret, long text, choice,
 *  number, tick box), as the server described it. A stored secret is never shown: the field
 *  stays empty and says leaving it empty keeps it. */
export default function ConnectorFieldControl({
  id,
  field,
  value,
  onChange,
  secret,
  stored,
}: {
  id: string;
  field: ConnectorField;
  value: string;
  onChange: (value: string) => void;
  secret?: boolean;
  stored?: boolean;
}) {
  const keep = secret && stored ? "•••• enregistré — laisser vide pour le conserver" : "";
  const required = secret ? !stored && field.required : field.required;
  switch (field.kind) {
    case "select":
      return (
        <select id={id} value={value || field.default} onChange={(e) => onChange(e.target.value)}>
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    case "checkbox":
      return (
        <input
          id={id}
          type="checkbox"
          checked={(value || field.default) === "true"}
          onChange={(e) => onChange(e.target.checked ? "true" : "false")}
        />
      );
    case "textarea":
      return (
        <textarea
          id={id}
          rows={4}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={keep}
          required={required}
          autoComplete="off"
          spellCheck={false}
        />
      );
    default:
      return (
        <input
          id={id}
          type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={keep}
          required={required}
          autoComplete={field.kind === "password" ? "new-password" : "off"}
        />
      );
  }
}
