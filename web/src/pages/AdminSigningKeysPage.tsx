import { useEffect, useState } from "react";
import { KeyRound, RotateCcw } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { SigningKeyInfo } from "../api/types";

export default function AdminSigningKeysPage() {
  const [keys, setKeys] = useState<SigningKeyInfo[] | null>(null);
  const [rotating, setRotating] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<SigningKeyInfo[]>("/admin/signing-keys").then(setKeys);
  };

  useEffect(load, []);

  const rotate = async () => {
    setRotating(true);
    try {
      await api.post("/admin/signing-keys/rotate");
      load();
    } finally {
      setRotating(false);
    }
  };

  const revoke = async (keyId: string) => {
    setError(null);
    try {
      await api.post(`/admin/signing-keys/${keyId}/revoke`);
      setConfirming(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "La révocation a échoué.");
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <KeyRound size={20} aria-hidden="true" /> Clés de signature
      </h1>

      <div className="card">
        <button className="button button--primary" onClick={rotate} disabled={rotating}>
          <RotateCcw size={14} aria-hidden="true" /> {rotating ? "Rotation…" : "Faire tourner la clé"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}
      <p className="muted small">
        Révoquer une clé retire la confiance aux signatures qu&apos;elle a produites (utile après une
        compromission). Si c&apos;est la clé active, une nouvelle clé est créée d&apos;abord.
      </p>
      <div className="card">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Identifiant</th>
              <th>Statut</th>
              <th>Créée le</th>
              <th>Retirée le</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {keys?.map((k) => (
              <tr key={k.key_id}>
                <td className="mono small">{k.key_id}</td>
                <td>
                  <span className={`badge badge--${k.status.toLowerCase()}`}>{k.status}</span>
                </td>
                <td>{new Date(k.created_at).toLocaleString("fr-FR")}</td>
                <td>{k.retired_at ? new Date(k.retired_at).toLocaleString("fr-FR") : "—"}</td>
                <td>
                  {k.status !== "REVOKED" &&
                    (confirming === k.key_id ? (
                      <>
                        <button className="button button--secondary button--sm" onClick={() => revoke(k.key_id)}>
                          Confirmer la révocation
                        </button>{" "}
                        <button className="button button--ghost button--sm" onClick={() => setConfirming(null)}>
                          Annuler
                        </button>
                      </>
                    ) : (
                      <button className="button button--ghost button--sm" onClick={() => setConfirming(k.key_id)}>
                        Révoquer
                      </button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
