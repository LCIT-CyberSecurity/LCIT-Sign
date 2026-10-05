import { useEffect, useState } from "react";
import { KeyRound, RotateCcw } from "lucide-react";
import { api } from "../api/client";
import type { SigningKeyInfo } from "../api/types";

export default function AdminSigningKeysPage() {
  const [keys, setKeys] = useState<SigningKeyInfo[] | null>(null);
  const [rotating, setRotating] = useState(false);

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

      <div className="card">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Identifiant</th>
              <th>Statut</th>
              <th>Créée le</th>
              <th>Retirée le</th>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
