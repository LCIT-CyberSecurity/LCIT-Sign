import type { ReactNode } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import Shell from "./components/Shell";
import LoginPage from "./pages/LoginPage";
import SignerAssignmentsPage from "./pages/SignerAssignmentsPage";
import SignerAssignmentDetailPage from "./pages/SignerAssignmentDetailPage";
import OperatorDocumentsPage from "./pages/OperatorDocumentsPage";
import OperatorCampaignsPage from "./pages/OperatorCampaignsPage";
import SignAllPage from "./pages/SignAllPage";
import SignedDocumentsPage from "./pages/SignedDocumentsPage";
import SignPage from "./pages/SignPage";
import SignRequestPage from "./pages/SignRequestPage";
import OperatorCampaignDetailPage from "./pages/OperatorCampaignDetailPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import AdminDirectoryPage from "./pages/AdminDirectoryPage";
import AdminMailPage from "./pages/AdminMailPage";
import AdminAuditPage from "./pages/AdminAuditPage";
import AdminSigningKeysPage from "./pages/AdminSigningKeysPage";
import AdminDiagnosticsPage from "./pages/AdminDiagnosticsPage";
import MySignaturesPage from "./pages/MySignaturesPage";
import PrepareDocumentPage from "./pages/PrepareDocumentPage";
import SignatureDetailPage from "./pages/SignatureDetailPage";

function RoleRoute({ allowed, children }: { allowed: boolean; children: ReactNode }) {
  return allowed ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  const { user, loading, hasRole } = useAuth();

  if (loading) {
    return (
      <div className="centered-page">
        <p className="muted">Chargement…</p>
      </div>
    );
  }

  if (!user) return <LoginPage />;

  const isOperator = hasRole("OPERATOR") || hasRole("ADMIN");
  const isAdmin = hasRole("ADMIN");

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<SignerAssignmentsPage />} />
        <Route path="/assignments/:id" element={<SignerAssignmentDetailPage />} />
        <Route path="/signatures" element={<MySignaturesPage />} />
        <Route path="/signatures/:id" element={<SignatureDetailPage />} />

        <Route
          path="/documents"
          element={
            <RoleRoute allowed={isOperator}>
              <OperatorDocumentsPage />
            </RoleRoute>
          }
        />
        <Route
          path="/documents/versions/:id/prepare"
          element={
            <RoleRoute allowed={isOperator}>
              <PrepareDocumentPage />
            </RoleRoute>
          }
        />
        <Route
          path="/sign"
          element={
            <RoleRoute allowed={isOperator}>
              <SignPage />
            </RoleRoute>
          }
        />
        <Route
          path="/sign/:id"
          element={
            <RoleRoute allowed={isOperator}>
              <SignRequestPage />
            </RoleRoute>
          }
        />
        <Route path="/sign-all/:campaignId" element={<SignAllPage />} />
        <Route
          path="/signed"
          element={
            <RoleRoute allowed={isOperator}>
              <SignedDocumentsPage />
            </RoleRoute>
          }
        />
        <Route
          path="/campaigns"
          element={
            <RoleRoute allowed={isOperator}>
              <OperatorCampaignsPage />
            </RoleRoute>
          }
        />
        <Route
          path="/campaigns/:id"
          element={
            <RoleRoute allowed={isOperator}>
              <OperatorCampaignDetailPage />
            </RoleRoute>
          }
        />

        <Route
          path="/admin/users"
          element={
            <RoleRoute allowed={isAdmin}>
              <AdminUsersPage />
            </RoleRoute>
          }
        />
        <Route
          path="/admin/directory"
          element={
            <RoleRoute allowed={isAdmin}>
              <AdminDirectoryPage />
            </RoleRoute>
          }
        />
        <Route
          path="/admin/mail"
          element={
            <RoleRoute allowed={isAdmin}>
              <AdminMailPage />
            </RoleRoute>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <RoleRoute allowed={isAdmin}>
              <AdminAuditPage />
            </RoleRoute>
          }
        />
        <Route
          path="/admin/signing-keys"
          element={
            <RoleRoute allowed={isAdmin}>
              <AdminSigningKeysPage />
            </RoleRoute>
          }
        />

        <Route
          path="/admin/diagnostics"
          element={
            <RoleRoute allowed={isAdmin}>
              <AdminDiagnosticsPage />
            </RoleRoute>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
