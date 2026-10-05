import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Megaphone, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Campaign } from "../api/types";

export default function OperatorCampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns);
  };

  useEffect(load, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name) return;
    setCreating(true);
    try {
      await api.post("/campaigns", { name });
      setName("");
      load();
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <Megaphone size={20} aria-hidden="true" /> Campagnes
      </h1>

      <form className="card form form--row" onSubmit={create}>
        <input
          placeholder="Nom de la campagne"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <button className="button button--primary" type="submit" disabled={creating}>
          <Plus size={14} aria-hidden="true" /> Créer
        </button>
      </form>

      <div className="card-list">
        {campaigns?.map((c) => (
          <Link key={c.id} to={`/campaigns/${c.id}`} className="card card--link">
            <div>
              <div className="card-title">{c.name}</div>
              <div className="muted small">
                {c.document_version_ids.length} document(s) — {c.target_mode}
              </div>
            </div>
            <div className="card-meta">
              <span className={`badge badge--${c.status.toLowerCase()}`}>{c.status}</span>
              {c.status === "ACTIVE" && (
                <span className="muted small">
                  {c.assignment_counts.SIGNED}/
                  {c.assignment_counts.PENDING +
                    c.assignment_counts.VIEWED +
                    c.assignment_counts.SIGNED +
                    c.assignment_counts.EXPIRED +
                    c.assignment_counts.CANCELLED}{" "}
                  signé(s)
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
