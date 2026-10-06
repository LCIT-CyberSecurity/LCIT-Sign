import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SignatureMethod, SignatureMethodOption } from "../api/types";

/** How the request is signed: LCIT Sign's own signature, or an eIDAS one through DocuSign. An
 *  option that cannot be used yet says why. Nothing is shown when the server offers no choice. */
export default function SignatureMethodPicker({
  value,
  onChange,
}: {
  value: SignatureMethod;
  onChange: (method: SignatureMethod) => void;
}) {
  const [options, setOptions] = useState<SignatureMethodOption[]>([]);

  useEffect(() => {
    api
      .get<SignatureMethodOption[]>("/campaigns/_meta/signature-methods")
      .then((all) => setOptions(Array.isArray(all) ? all : []))
      .catch(() => setOptions([]));
  }, []);

  if (options.length < 2) return null;
  return (
    <div className="card" data-testid="method-card">
      <div className="card-title">Méthode de signature</div>
      <fieldset className="method-choice">
        <legend className="muted small">Comment les signataires signent</legend>
        {options.map((option) => (
          <label
            key={option.method}
            className={`method-choice__option${value === option.method ? " is-selected" : ""}${
              option.available ? "" : " is-disabled"
            }`}
          >
            <input
              type="radio"
              name="signature-method"
              value={option.method}
              checked={value === option.method}
              disabled={!option.available}
              onChange={() => onChange(option.method)}
            />
            <span>
              <strong>{option.label}</strong>
              <span className="muted small">{option.description}</span>
              {!option.available && option.unavailable_reason && (
                <span className="muted small">{option.unavailable_reason}</span>
              )}
            </span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}
