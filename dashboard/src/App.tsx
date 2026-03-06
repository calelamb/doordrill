import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { ManagerChatPanel } from "./components/ManagerChatPanel";
import { Sidebar } from "./components/Sidebar";
import { clearStoredAuth, getValidStoredAuth } from "./lib/auth";
import { ManagerFeedPage } from "./pages/ManagerFeedPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ActionsPage } from "./pages/ActionsPage";
import { AssignmentCreatePage } from "./pages/AssignmentCreatePage";
import { CoachingLabPage } from "./pages/CoachingLabPage";
import { ExplorerPage } from "./pages/ExplorerPage";
import { LoginPage } from "./pages/LoginPage";
import { LiveSessionPage } from "./pages/LiveSessionPage";
import { ManagerReplayPage } from "./pages/ManagerReplayPage";
import { RepProgressPage } from "./pages/RepProgressPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RiskIntelligencePage } from "./pages/RiskIntelligencePage";
import { ScenarioIntelligencePage } from "./pages/ScenarioIntelligencePage";

function RootRedirect() {
  const auth = getValidStoredAuth();
  return <Navigate to={auth ? "/manager/feed" : "/login"} replace />;
}

function ProtectedLayout() {
  const location = useLocation();
  const auth = getValidStoredAuth();
  const [isChatOpen, setIsChatOpen] = useState(false);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
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
        <Outlet />
      </div>
      <ManagerChatPanel
        isOpen={isChatOpen}
        managerId={auth.user.id}
        onClose={() => setIsChatOpen(false)}
        onToggle={() => setIsChatOpen((current) => !current)}
      />
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
          <Route path="/manager/actions" element={<ActionsPage />} />
          <Route path="/manager/assignments/new" element={<AssignmentCreatePage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
