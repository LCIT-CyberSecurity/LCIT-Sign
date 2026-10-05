import type { ReactNode } from "react";

/** A friendly empty state: an icon, what is missing, and (optionally) what to do. */
export default function EmptyState({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__icon" aria-hidden="true">
        {icon}
      </span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
