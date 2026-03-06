import { ActivitySquare, BarChart2, Compass, History, LayoutDashboard, LogOut, Scale, Shield, TreePine } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { clearStoredAuth, getValidStoredAuth } from "../lib/auth";

export function Sidebar() {
    const location = useLocation();
    const navigate = useNavigate();
    const auth = getValidStoredAuth();
    const user = auth?.user;
    const initials = user?.name
        ?.split(" ")
        .map((chunk) => chunk[0]?.toUpperCase())
        .slice(0, 2)
        .join("") || "MG";

    const isFeed = location.pathname.startsWith("/manager/feed") || location.pathname.includes("/manager/sessions/");
    const isAnalytics = location.pathname.startsWith("/manager/analytics");
    const isRisk = location.pathname.startsWith("/manager/risk");
    const isScenarios = location.pathname.startsWith("/manager/scenarios");
    const isCoaching = location.pathname.startsWith("/manager/coaching");
    const isExplorer = location.pathname.startsWith("/manager/explorer");
    const isActions = location.pathname.startsWith("/manager/actions");

    return (
        <aside className="w-[220px] shrink-0 bg-white/30 backdrop-blur-2xl border-r border-white/20 h-screen sticky top-0 flex flex-col">
            <div className="flex items-center gap-2.5 px-6 pt-6 pb-8">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-white shadow-lg shadow-accent/25">
                    <TreePine className="h-5 w-5" />
                </div>
                <span className="text-lg font-bold tracking-tight text-ink">DoorDrill</span>
            </div>

            <nav className="flex-1 px-4 space-y-1">
                <Link
                    to="/manager/feed"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isFeed
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <LayoutDashboard className="w-4.5 h-4.5 min-w-4.5" />
                    Feed
                </Link>

                <Link
                    to="/manager/analytics"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isAnalytics
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <BarChart2 className="w-4.5 h-4.5 min-w-4.5" />
                    Command Center
                </Link>

                <Link
                    to="/manager/risk"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isRisk
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <Shield className="w-4.5 h-4.5 min-w-4.5" />
                    Risk Intelligence
                </Link>

                <Link
                    to="/manager/coaching"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isCoaching
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <Scale className="w-4.5 h-4.5 min-w-4.5" />
                    Coaching
                </Link>

                <Link
                    to="/manager/scenarios"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isScenarios
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <ActivitySquare className="w-4.5 h-4.5 min-w-4.5" />
                    Scenarios
                </Link>

                <Link
                    to="/manager/explorer"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isExplorer
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <Compass className="w-4.5 h-4.5 min-w-4.5" />
                    Explorer
                </Link>

                <Link
                    to="/manager/actions"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isActions
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <History className="w-4.5 h-4.5 min-w-4.5" />
                    Actions
                </Link>
            </nav>

            <div className="p-4 mt-auto border-t border-white/20">
                <button
                    onClick={() => {
                        clearStoredAuth();
                        navigate("/login", { replace: true });
                    }}
                    className="w-full flex items-center gap-3 p-2 rounded-xl hover:bg-white/40 transition-colors text-left group"
                >
                    <div className="w-8 h-8 rounded-full bg-accent text-white flex items-center justify-center text-xs font-bold shrink-0">
                        {initials}
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-bold text-ink truncate">{user?.name ?? "Manager"}</div>
                        <div className="text-xs text-muted truncate">{user?.role ?? "manager"}</div>
                    </div>
                    <LogOut className="w-4 h-4 text-muted group-hover:text-ink transition-colors" />
                </button>
            </div>
        </aside>
    );
}
