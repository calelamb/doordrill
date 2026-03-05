import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { clearStoredAuth, getValidStoredAuth } from "./lib/auth";
import { ManagerFeedPage } from "./pages/ManagerFeedPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ActionsPage } from "./pages/ActionsPage";
import { AssignmentCreatePage } from "./pages/AssignmentCreatePage";
import { LoginPage } from "./pages/LoginPage";
import { ManagerReplayPage } from "./pages/ManagerReplayPage";
import { RepProgressPage } from "./pages/RepProgressPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function RootRedirect() {
  const auth = getValidStoredAuth();
  return <Navigate to={auth ? "/manager/feed" : "/login"} replace />;
}

function ProtectedLayout() {
  const location = useLocation();
  const auth = getValidStoredAuth();

  if (!auth) {
    clearStoredAuth();
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 overflow-y-auto w-full">
        <Outlet />
      </div>
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
          <Route path="/manager/sessions/:id/replay" element={<ManagerReplayPage />} />
          <Route path="/manager/reps/:id/progress" element={<RepProgressPage />} />
          <Route path="/manager/analytics" element={<AnalyticsPage />} />
          <Route path="/manager/actions" element={<ActionsPage />} />
          <Route path="/manager/assignments/new" element={<AssignmentCreatePage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
