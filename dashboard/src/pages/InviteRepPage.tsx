import { useNavigate } from "react-router-dom";

import { clearStoredAuth } from "../lib/auth";
import { InviteRepModal } from "../components/InviteRepModal";

export function InviteRepPage() {
  const navigate = useNavigate();

  return (
    <main className="min-h-screen px-6 py-10">
      <div className="flex min-h-[calc(100vh-5rem)] items-center justify-center">
        <InviteRepModal
          onClose={() => navigate("/manager/analytics")}
          onAuthError={() => {
            clearStoredAuth();
            navigate("/login", { replace: true });
          }}
        />
      </div>
    </main>
  );
}
