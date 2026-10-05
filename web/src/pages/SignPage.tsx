import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PenLine, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Campaign } from "../api/types";

/** Where a request for signature starts: choose who signs, what, for whom — then send.
 *  Requests still being prepared are listed to be picked up again; once sent, they are
 *  followed in Campagnes. */
export default function SignPage() {
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns);
  }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await api.post<Campaign>("/campaigns", { name: name.trim() });
      navigate(`/sign/${created.id}`);
    } finally {
      setCreating(false);
    }
  };

  const drafts = (campaigns ?? [])
    .filter((c) => c.status === "DRAFT")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <PenLine size={22} aria-hidden="true" /> Faire signer
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            Faites signer un ou plusieurs documents : choisissez qui signe, déposez les documents, placez
            les éléments, puis envoyez.
          </p>
        </div>
      </div>

      <form className="card form" onSubmit={create} aria-label="Nouvelle demande de signature">
        <div className="card-title">Nouvelle demande de signature</div>
        <div className="inline-create">
          <input
            placeholder="Nom de la demande (ex : PSSI 2026)"
            aria-label="Nom de la demande"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <button className="button button--primary" type="submit" disabled={creating}>
            <Plus size={14} aria-hidden="true" /> Commencer
          </button>
        </div>
      </form>

      <section>
        <h2 className="card-title">En préparation</h2>
        {drafts.length === 0 ? (
          <p className="muted">Aucune demande en préparation.</p>
        ) : (
          <div className="card-list">
            {drafts.map((c) => (
              <Link key={c.id} to={`/sign/${c.id}`} className="card card--link">
                <div>
                  <div className="card-title">{c.name}</div>
                  <div className="muted small">
                    {c.documents.length} document(s) — {c.roles.length} signataire(s) défini(s)
                  </div>
                </div>
                <div className="card-meta">Reprendre</div>
              </Link>
            ))}
          </div>
        )}
        <p className="muted small">
          Les demandes envoyées se suivent dans <Link to="/campaigns">Suivi</Link>.
        </p>
      </section>
    </div>
  );
}
