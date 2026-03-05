import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { ManagerFeedPage } from "./pages/ManagerFeedPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ActionsPage } from "./pages/ActionsPage";
import { AssignmentCreatePage } from "./pages/AssignmentCreatePage";
import { RepProgressPage } from "./pages/RepProgressPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen">
        <Sidebar />

        {/* Main Content Area */}
        <div className="flex-1 overflow-y-auto w-full">
          <Routes>
            <Route path="/" element={<Navigate to="/manager/feed" replace />} />
            <Route path="/manager/feed" element={<ManagerFeedPage />} />

            {/* The replay route technically renders the same page but with an active session implicitly handled.
                In a real app, ManagerFeedPage would capture the :id from useParams(). For now, we map it to Feed. */}
            <Route path="/manager/sessions/:id/replay" element={<ManagerFeedPage />} />

            <Route path="/manager/reps/:id/progress" element={<RepProgressPage />} />
            <Route path="/manager/analytics" element={<AnalyticsPage />} />
            <Route path="/manager/actions" element={<ActionsPage />} />
            <Route path="/manager/assignments/new" element={<AssignmentCreatePage />} />

            {/* 404 Fallback */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
