import { useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { UploadCloud } from "lucide-react";

/** Drop files here, or click to browse. It only hands the files over: what to do
 *  with them (and what is accepted) is the page's business. */
export default function UploadDropzone({
  onFiles,
  disabled,
  accept = "application/pdf,.pdf",
  hint,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  accept?: string;
  hint?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const take = (list: FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (files.length > 0 && !disabled) onFiles(files);
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.current?.click();
    }
  };

  return (
    <div
      className={`dropzone${over ? " dropzone--over" : ""}${disabled ? " dropzone--disabled" : ""}`}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label="Déposer des fichiers ou parcourir"
      data-testid="dropzone"
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={onKey}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <UploadCloud size={28} aria-hidden="true" />
      <strong>Glissez vos documents ici</strong>
      <span className="muted small">ou cliquez pour parcourir{hint ? ` — ${hint}` : ""}</span>
      <input
        ref={input}
        type="file"
        multiple
        accept={accept}
        hidden
        data-testid="dropzone-input"
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
