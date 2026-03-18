import { Suspense, lazy, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { clearStoredAuth, getValidStoredAuth } from "./lib/auth";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";

const ManagerFeedPage = lazy(async () => ({ default: (await import("./pages/ManagerFeedPage")).ManagerFeedPage }));
const AnalyticsPage = lazy(async () => ({ default: (await import("./pages/AnalyticsPage")).AnalyticsPage }));
const ActionsPage = lazy(async () => ({ default: (await import("./pages/ActionsPage")).ActionsPage }));
const AssignmentCreatePage = lazy(
  async () => ({ default: (await import("./pages/AssignmentCreatePage")).AssignmentCreatePage })
);
const CoachingLabPage = lazy(async () => ({ default: (await import("./pages/CoachingLabPage")).CoachingLabPage }));
const ExplorerPage = lazy(async () => ({ default: (await import("./pages/ExplorerPage")).ExplorerPage }));
const InviteRepPage = lazy(async () => ({ default: (await import("./pages/InviteRepPage")).InviteRepPage }));
const LiveSessionPage = lazy(async () => ({ default: (await import("./pages/LiveSessionPage")).LiveSessionPage }));
const KnowledgeBasePage = lazy(
  async () => ({ default: (await import("./pages/KnowledgeBasePage")).KnowledgeBasePage })
);
const ManagerReplayPage = lazy(
  async () => ({ default: (await import("./pages/ManagerReplayPage")).ManagerReplayPage })
);
const OrganizationSettingsPage = lazy(
  async () => ({ default: (await import("./pages/OrganizationSettingsPage")).OrganizationSettingsPage })
);
const RepProgressPage = lazy(async () => ({ default: (await import("./pages/RepProgressPage")).RepProgressPage }));
const RiskIntelligencePage = lazy(
  async () => ({ default: (await import("./pages/RiskIntelligencePage")).RiskIntelligencePage })
);
const ScenarioCreatePage = lazy(
  async () => ({ default: (await import("./pages/ScenarioCreatePage")).ScenarioCreatePage })
);
const ScenarioIntelligencePage = lazy(
  async () => ({ default: (await import("./pages/ScenarioIntelligencePage")).ScenarioIntelligencePage })
);
const ManagerChatPanel = lazy(
  async () => ({ default: (await import("./components/ManagerChatPanel")).ManagerChatPanel })
);

function RootRedirect() {
  const auth = getValidStoredAuth();
  return <Navigate to={auth ? "/manager/feed" : "/login"} replace />;
}

function getModifierKeyLabel(): string {
  if (typeof navigator === "undefined") {
    return "Ctrl+K";
  }
  return /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl+K";
}

function ProtectedRouteFallback() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="rounded-[28px] border border-white/30 bg-white/65 px-6 py-8 text-sm text-muted shadow-lg backdrop-blur-xl">
        Loading dashboard...
      </div>
    </div>
  );
}

function ManagerChatLauncher({ onOpen }: { onOpen: () => void }) {
  const shortcutLabel = getModifierKeyLabel();

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="Open manager AI chat"
      title={shortcutLabel}
      className="fixed bottom-6 right-6 z-50 inline-flex items-center gap-2 rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-white shadow-xl shadow-accent/25 transition hover:bg-accent-hover"
    >
      <Sparkles className="h-4 w-4" />
      <span>Ask AI</span>
      <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-medium text-white/90">{shortcutLabel}</span>
    </button>
  );
}

function ChatPanelFallback({ open }: { open: boolean }) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-ink/15" />
      <aside className="absolute right-0 top-0 h-full w-full border-l border-white/30 bg-white/80 shadow-2xl backdrop-blur-2xl sm:w-[420px]" />
    </div>
  );
}

function ProtectedLayout() {
  const location = useLocation();
  const auth = getValidStoredAuth();
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [hasRequestedChatPanel, setHasRequestedChatPanel] = useState(false);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setHasRequestedChatPanel(true);
        setIsChatOpen((current) => !current);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  if (!auth) {
    clearStoredAuth();
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  if (!["manager", "admin"].includes(auth.user.role)) {
    clearStoredAuth();
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 overflow-y-auto w-full">
        <Suspense fallback={<ProtectedRouteFallback />}>
          <Outlet />
        </Suspense>
      </div>
      {!hasRequestedChatPanel ? (
        <ManagerChatLauncher
          onOpen={() => {
            setHasRequestedChatPanel(true);
            setIsChatOpen(true);
          }}
        />
      ) : (
        <Suspense fallback={<ChatPanelFallback open={isChatOpen} />}>
          <ManagerChatPanel
            isOpen={isChatOpen}
            managerId={auth.user.id}
            onClose={() => setIsChatOpen(false)}
            onToggle={() => setIsChatOpen((current) => !current)}
          />
        </Suspense>
      )}
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/manager/feed" element={<ManagerFeedPage />} />
          <Route path="/manager/sessions/:id/live" element={<LiveSessionPage />} />
          <Route path="/manager/sessions/:id/replay" element={<ManagerReplayPage />} />
          <Route path="/manager/reps/:id/progress" element={<RepProgressPage />} />
          <Route path="/manager/analytics" element={<AnalyticsPage />} />
          <Route path="/manager/risk" element={<RiskIntelligencePage />} />
          <Route path="/manager/scenarios" element={<ScenarioIntelligencePage />} />
          <Route path="/manager/coaching" element={<CoachingLabPage />} />
          <Route path="/manager/explorer" element={<ExplorerPage />} />
          <Route path="/knowledge-base" element={<KnowledgeBasePage />} />
          <Route path="/manager/actions" element={<ActionsPage />} />
          <Route path="/manager/assignments/new" element={<AssignmentCreatePage />} />
          <Route path="/settings/organization" element={<OrganizationSettingsPage />} />
          <Route path="/scenarios/new" element={<ScenarioCreatePage />} />
          <Route path="/reps/invite" element={<InviteRepPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
