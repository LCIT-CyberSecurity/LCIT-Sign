import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** A destructive action behind a deliberate second click, with no modal: the
 *  first click asks, the second one does it, "Annuler" backs out. */
export default function ConfirmButton({
  children,
  confirmLabel,
  onConfirm,
  className = "button button--ghost button--sm",
  confirmClassName = "button button--danger button--sm",
  disabled,
}: {
  children: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  className?: string;
  /** The look of the second click: danger by default, plain for a safe action (sending). */
  confirmClassName?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>
        {children}
      </button>
    );
  }
  return (
    <span className="confirm-inline">
      <button
        type="button"
        className={confirmClassName}
        onClick={async () => {
          await onConfirm();
          setAsking(false);
        }}
      >
        {confirmLabel ?? t("common.confirmDelete")}
      </button>
      <button type="button" className="button button--ghost button--sm" onClick={() => setAsking(false)}>
        {t("common.cancel")}
      </button>
    </span>
  );
}
