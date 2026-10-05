import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { api } from "../api/client";
import type { AdminUser, Role } from "../api/types";

const ALL_ROLES: Role[] = ["SIGNER", "OPERATOR", "ADMIN"];

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);

  const load = () => {
    api.get<AdminUser[]>("/admin/users").then(setUsers);
  };

  useEffect(load, []);

  const toggleRole = async (user: AdminUser, role: Role) => {
    if (user.roles.includes(role)) {
      await api.del(`/admin/users/${user.id}/roles/${role}`);
    } else {
      await api.post(`/admin/users/${user.id}/roles`, { role });
    }
    load();
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <Users size={20} aria-hidden="true" /> Utilisateurs
      </h1>
      <div className="card">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Utilisateur</th>
              <th>Actif</th>
              {ALL_ROLES.map((role) => (
                <th key={role}>{role}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users?.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.display_name}
                  <div className="muted small">{u.email}</div>
                </td>
                <td>{u.active ? "Oui" : "Non"}</td>
                {ALL_ROLES.map((role) => (
                  <td key={role}>
                    <input
                      type="checkbox"
                      checked={u.roles.includes(role)}
                      onChange={() => toggleRole(u, role)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
