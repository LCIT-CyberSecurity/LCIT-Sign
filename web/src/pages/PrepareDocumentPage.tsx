import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Lock, Plus, Save, Trash2, UserRound } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import PdfPages, { type PageSize } from "../prepare/PdfPages";
import { clampRect, moveRect, placeCentered, pointToFraction, resizeRect, tidy, type Rect } from "../prepare/geometry";
import { KIND_BY_ID, KINDS, MAX_RECIPIENTS, roleColor, type FieldKind } from "../prepare/kinds";

export interface EditorField extends Rect {
  id: string;
  page: number;
  kind: FieldKind;
  label: string;
  required: boolean;
  role: number;
  group_key: string | null;
}

interface FieldsResponse {
  editable: boolean;
  document_title: string;
  version_label: string;
  status: string;
  fields: EditorField[];
}

const DRAG_TYPE = "application/x-lcit-element";

type Gesture =
  | { id: string; mode: "move" | "resize"; startX: number; startY: number; origin: Rect; bounds: DOMRect }
  | null;

function FieldBox({
  field,
  selected,
  editable,
  onSelect,
  onChange,
  overlay,
}: {
  field: EditorField;
  selected: boolean;
  editable: boolean;
  onSelect: () => void;
  onChange: (rect: Rect) => void;
  overlay: HTMLDivElement | null;
}) {
  const gesture = useRef<Gesture>(null);
  const meta = KIND_BY_ID[field.kind];
  const Icon = meta.icon;
  const color = roleColor(field.role);

  const begin = (mode: "move" | "resize") => (e: PointerEvent<HTMLElement>) => {
    onSelect();
    if (!editable || !overlay) return;
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    gesture.current = {
      id: field.id,
      mode,
      startX: e.clientX,
      startY: e.clientY,
      origin: { x: field.x, y: field.y, width: field.width, height: field.height },
      bounds: overlay.getBoundingClientRect(),
    };
  };

  const track = (e: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g) return;
    const dx = (e.clientX - g.startX) / g.bounds.width;
    const dy = (e.clientY - g.startY) / g.bounds.height;
    onChange(g.mode === "move" ? moveRect(g.origin, dx, dy) : resizeRect(g.origin, dx, dy));
  };

  const end = (e: PointerEvent<HTMLElement>) => {
    if (gesture.current) e.currentTarget.releasePointerCapture(e.pointerId);
    gesture.current = null;
  };

  return (
    <div
      className={`prep-field${selected ? " prep-field--selected" : ""}${editable ? "" : " prep-field--locked"}`}
      style={{
        left: `${field.x * 100}%`,
        top: `${field.y * 100}%`,
        width: `${field.width * 100}%`,
        height: `${field.height * 100}%`,
        borderColor: color,
        background: `${color}1f`,
        color,
      }}
      data-testid={`field-${field.kind}`}
      data-role={field.role}
      onPointerDown={begin("move")}
      onPointerMove={track}
      onPointerUp={end}
      onPointerCancel={end}
    >
      <span className="prep-field__tag" style={{ background: color }}>
        {field.role}
      </span>
      <Icon size={13} aria-hidden="true" />
      <span className="prep-field__label">{field.label || meta.label}</span>
      {selected && editable && (
        <span
          className="prep-field__handle"
          style={{ background: color }}
          data-testid="resize-handle"
          onPointerDown={begin("resize")}
          onPointerMove={track}
          onPointerUp={end}
          onPointerCancel={end}
        />
      )}
    </div>
  );
}

export default function PrepareDocumentPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [info, setInfo] = useState<FieldsResponse | null>(null);
  const [pages, setPages] = useState<PageSize[]>([]);
  const [fields, setFields] = useState<EditorField[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [recipients, setRecipients] = useState(1);
  const [activeRole, setActiveRole] = useState(1);
  const [armed, setArmed] = useState<FieldKind | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<FieldsResponse>(`/documents/versions/${id}/fields`),
      api.get<PageSize[]>(`/documents/versions/${id}/pages`),
    ])
      .then(([loaded, sizes]) => {
        setInfo(loaded);
        setFields(loaded.fields);
        setPages(sizes);
        setRecipients(Math.max(1, ...loaded.fields.map((f) => f.role)));
      })
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "Document introuvable."));
  }, [id]);

  const editable = info?.editable ?? false;
  const selected = fields.find((f) => f.id === selectedId) ?? null;

  const update = useCallback((fieldId: string, patch: Partial<EditorField>) => {
    setFields((all) => all.map((f) => (f.id === fieldId ? { ...f, ...patch } : f)));
    setDirty(true);
    setMessage(null);
  }, []);

  const place = useCallback(
    (kind: FieldKind, page: number, point: { x: number; y: number }) => {
      const rect = tidy(placeCentered(kind, point));
      const created: EditorField = {
        id: crypto.randomUUID(),
        page,
        ...rect,
        kind,
        label: "",
        required: kind === "TEXT",
        role: activeRole,
        group_key: null,
      };
      setFields((all) => [...all, created]);
      setSelectedId(created.id);
      setDirty(true);
      setMessage(null);
      setArmed(null);
    },
    [activeRole],
  );

  const remove = useCallback((fieldId: string) => {
    setFields((all) => all.filter((f) => f.id !== fieldId));
    setSelectedId(null);
    setDirty(true);
    setMessage(null);
  }, []);

  // Keyboard: Delete removes, arrows nudge by half a percent, Escape lets go.
  useEffect(() => {
    if (!editable) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (e.key === "Escape") {
        setSelectedId(null);
        setArmed(null);
        return;
      }
      if (!selectedId) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        remove(selectedId);
      }
      const step = e.shiftKey ? 0.02 : 0.005;
      const nudge: Record<string, [number, number]> = {
        ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
      };
      const delta = nudge[e.key];
      if (delta) {
        e.preventDefault();
        setFields((all) =>
          all.map((f) => (f.id === selectedId ? { ...f, ...tidy(moveRect(f, delta[0], delta[1])) } : f)),
        );
        setDirty(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editable, selectedId, remove]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = async (): Promise<boolean> => {
    setSaving(true);
    setError(null);
    try {
      const saved = await api.put<FieldsResponse>(`/documents/versions/${id}/fields`, {
        fields: fields.map(({ id: fieldId, page, x, y, width, height, kind, label, required, role, group_key }) => ({
          id: fieldId, page, ...tidy({ x, y, width, height }), kind, label, required, role, group_key,
        })),
      });
      setFields(saved.fields);
      setDirty(false);
      setMessage(`Enregistré — ${saved.fields.length} élément(s).`);
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "L'enregistrement a échoué.");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    if (dirty && !(await save())) return;
    setError(null);
    try {
      await api.post(`/documents/versions/${id}/publish`);
      navigate("/documents");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "La publication a échoué.");
    }
  };

  const onDrop = (page: number, overlay: HTMLDivElement) => (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const kind = e.dataTransfer.getData(DRAG_TYPE) as FieldKind;
    if (!kind || !KIND_BY_ID[kind]) return;
    place(kind, page, pointToFraction(e.clientX, e.clientY, overlay.getBoundingClientRect()));
  };

  const counts = useMemo(() => {
    const byRole = new Map<number, number>();
    fields.forEach((f) => byRole.set(f.role, (byRole.get(f.role) ?? 0) + 1));
    return byRole;
  }, [fields]);

  if (loadError) return <p className="error-text">{loadError}</p>;
  if (!info) return <p className="muted">Chargement…</p>;

  const pagesWithFields = new Set(fields.map((f) => f.page)).size;

  return (
    <div className="stack prep">
      <Link to="/documents" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> Documents
      </Link>
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            Préparer le document
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            {info.document_title} — version {info.version_label}{" "}
            <span className={`badge badge--${info.status.toLowerCase()}`}>{info.status}</span>
          </p>
        </div>
        {editable && (
          <div className="row-actions">
            <span className="muted small" data-testid="prep-status">
              {dirty ? "Modifications non enregistrées" : message ?? `${fields.length} élément(s) sur ${pagesWithFields} page(s)`}
            </span>
            <button className="button button--secondary" onClick={() => void save()} disabled={saving || !dirty}>
              <Save size={14} aria-hidden="true" /> {saving ? "Enregistrement…" : "Enregistrer"}
            </button>
            <ConfirmButton
              className="button button--primary"
              confirmLabel="Publier — les éléments seront figés"
              onConfirm={publish}
            >
              <CheckCircle2 size={14} aria-hidden="true" /> Publier
            </ConfirmButton>
          </div>
        )}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!editable && (
        <p className="prep-locked-note">
          <Lock size={14} aria-hidden="true" /> Version publiée : les éléments sont figés, comme le document.
        </p>
      )}

      <div className="prep-layout">
        <aside className="prep-rail" aria-label="Palette">
          {editable && (
            <>
              <div className="prep-rail__title">Destinataires</div>
              <p className="muted small" style={{ margin: "0 0 8px" }}>
                Choisissez qui remplit, puis placez ses éléments. Les destinataires signent dans l&apos;ordre.
              </p>
              <ul className="prep-roles">
                {Array.from({ length: recipients }, (_, i) => i + 1).map((role) => (
                  <li key={role}>
                    <button
                      type="button"
                      className={`prep-role${activeRole === role ? " prep-role--active" : ""}`}
                      style={{ ["--role" as string]: roleColor(role) }}
                      aria-pressed={activeRole === role}
                      onClick={() => setActiveRole(role)}
                    >
                      <span className="prep-role__dot" />
                      <UserRound size={14} aria-hidden="true" />
                      Signataire {role}
                      <span className="prep-role__count">{counts.get(role) ?? 0}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className="button button--ghost button--sm"
                disabled={recipients >= MAX_RECIPIENTS}
                onClick={() => {
                  setRecipients((n) => n + 1);
                  setActiveRole(recipients + 1);
                }}
              >
                <Plus size={13} aria-hidden="true" /> Ajouter un destinataire
              </button>

              <div className="prep-rail__title" style={{ marginTop: 18 }}>
                Éléments à placer
              </div>
              <p className="muted small" style={{ margin: "0 0 8px" }}>
                Glissez sur le document, ou cliquez puis cliquez sur la page.
              </p>
              <ul className="prep-palette">
                {KINDS.map((meta) => {
                  const Icon = meta.icon;
                  return (
                    <li key={meta.kind}>
                      <button
                        type="button"
                        draggable
                        className={`prep-tool${armed === meta.kind ? " prep-tool--armed" : ""}`}
                        data-testid={`tool-${meta.kind}`}
                        aria-pressed={armed === meta.kind}
                        title={meta.hint}
                        onDragStart={(e) => {
                          e.dataTransfer.setData(DRAG_TYPE, meta.kind);
                          e.dataTransfer.effectAllowed = "copy";
                        }}
                        onClick={() => setArmed(armed === meta.kind ? null : meta.kind)}
                      >
                        <Icon size={15} aria-hidden="true" />
                        <span>
                          {meta.label}
                          <small>{meta.automatic ? "Automatique" : "À saisir"}</small>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          {!editable && <p className="muted small">Les destinataires et éléments sont en lecture seule.</p>}
        </aside>

        <section className="prep-canvas">
          <PdfPages
            url={`/api/documents/versions/${id}/content`}
            pages={pages}
            renderOverlay={(page, frame) => (
              <div
                className={`prep-overlay${armed ? " prep-overlay--armed" : ""}`}
                data-testid={`overlay-${page.number}`}
                onDragOver={(e) => editable && e.preventDefault()}
                onDrop={(e) => editable && frame && onDrop(page.number, frame)(e)}
                onPointerDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (armed && editable && frame) {
                    place(armed, page.number, pointToFraction(e.clientX, e.clientY, frame.getBoundingClientRect()));
                  } else {
                    setSelectedId(null);
                  }
                }}
              >
                {fields
                  .filter((f) => f.page === page.number)
                  .map((f) => (
                    <FieldBox
                      key={f.id}
                      field={f}
                      selected={f.id === selectedId}
                      editable={editable}
                      overlay={frame}
                      onSelect={() => setSelectedId(f.id)}
                      onChange={(rect) => update(f.id, clampRect(rect))}
                    />
                  ))}
              </div>
            )}
          />
        </section>

        <aside className="prep-props" aria-label="Propriétés">
          <div className="prep-rail__title">Propriétés</div>
          {!selected && <p className="muted small">Sélectionnez un élément sur le document pour le régler.</p>}
          {selected && (
            <div className="stack" style={{ gap: 12 }}>
              <div>
                <strong>{KIND_BY_ID[selected.kind].label}</strong>
                <div className="muted small">{KIND_BY_ID[selected.kind].hint}</div>
              </div>
              <label>
                Destinataire
                <select
                  value={selected.role}
                  disabled={!editable}
                  onChange={(e) => update(selected.id, { role: Number(e.target.value) })}
                >
                  {Array.from({ length: recipients }, (_, i) => i + 1).map((role) => (
                    <option key={role} value={role}>
                      Signataire {role}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Libellé
                <input
                  value={selected.label}
                  maxLength={120}
                  disabled={!editable}
                  placeholder={KIND_BY_ID[selected.kind].label}
                  onChange={(e) => update(selected.id, { label: e.target.value })}
                />
              </label>
              {selected.kind === "TEXT" && (
                <>
                  <label className="consent-row">
                    <input
                      type="checkbox"
                      checked={selected.required}
                      disabled={!editable}
                      onChange={(e) => update(selected.id, { required: e.target.checked })}
                    />
                    <span>Obligatoire</span>
                  </label>
                  <label>
                    Saisie partagée (clé)
                    <input
                      value={selected.group_key ?? ""}
                      maxLength={60}
                      disabled={!editable}
                      placeholder="ex : societe"
                      onChange={(e) => update(selected.id, { group_key: e.target.value || null })}
                    />
                    <span className="muted small">
                      Les champs de même clé se remplissent une seule fois, sur tous les documents.
                    </span>
                  </label>
                </>
              )}
              {editable && (
                <button className="button button--ghost button--sm" onClick={() => remove(selected.id)}>
                  <Trash2 size={13} aria-hidden="true" /> Supprimer l&apos;élément
                </button>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
