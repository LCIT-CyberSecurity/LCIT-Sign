import { useEffect, useState } from "react";
import { FileSignature, ShieldCheck } from "lucide-react";

type ApiStatus = "checking" | "online" | "offline";

async function checkApiHealth(): Promise<ApiStatus> {
  try {
    const response = await fetch("/api/health");
    return response.ok ? "online" : "offline";
  } catch {
    return "offline";
  }
}

export default function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    checkApiHealth().then(setApiStatus);
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <FileSignature size={22} aria-hidden="true" />
          <span>LCIT Sign</span>
        </div>
        <div className={`status-pill status-pill--${apiStatus}`}>
          <ShieldCheck size={14} aria-hidden="true" />
          {apiStatus === "checking" && "Vérification..."}
          {apiStatus === "online" && "API connectée"}
          {apiStatus === "offline" && "API indisponible"}
        </div>
      </header>
      <main className="app-main">
        <div className="card">
          <h1>Plateforme de signature interne</h1>
          <p>
            L&apos;interface signataire, opérateur et administration sera construite au fil des
            prochaines phases du projet.
          </p>
        </div>
      </main>
    </div>
  );
}
