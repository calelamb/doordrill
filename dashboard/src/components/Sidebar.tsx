import { useEffect, useState } from "react";
import { ActivitySquare, BarChart2, BookOpenText, ClipboardList, Compass, History, LayoutDashboard, LogOut, Scale, Shield, TreePine, UserPlus } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { clearStoredAuth, getValidStoredAuth } from "../lib/auth";
import { fetchLiveSessions } from "../lib/api";

export function Sidebar() {
    const location = useLocation();
    const navigate = useNavigate();
    const auth = getValidStoredAuth();
    const user = auth?.user;
    const managerId = user?.id ?? "";
    const initials = user?.name
        ?.split(" ")
        .map((chunk) => chunk[0]?.toUpperCase())
        .slice(0, 2)
        .join("") || "MG";
    const [liveCount, setLiveCount] = useState(0);

    const isFeed = location.pathname.startsWith("/manager/feed") || location.pathname.includes("/manager/sessions/");
    const isAnalytics = location.pathname.startsWith("/manager/analytics");
    const isRisk = location.pathname.startsWith("/manager/risk");
    const isScenarios = location.pathname.startsWith("/manager/scenarios");
    const isCoaching = location.pathname.startsWith("/manager/coaching");
    const isExplorer = location.pathname.startsWith("/manager/explorer");
    const isKnowledgeBase = location.pathname.startsWith("/knowledge-base");
    const isActions = location.pathname.startsWith("/manager/actions");
    const isAssignments = location.pathname.startsWith("/manager/assignments");
    const isInvite = location.pathname.startsWith("/reps/invite");

    useEffect(() => {
        if (!managerId) {
            setLiveCount(0);
            return;
        }

        let cancelled = false;
        const loadLiveCount = async () => {
            try {
                const response = await fetchLiveSessions(managerId);
                if (!cancelled) {
                    setLiveCount(response.live_sessions.length);
                }
            } catch {
                if (!cancelled) {
                    setLiveCount(0);
                }
            }
        };

        void loadLiveCount();
        const intervalId = window.setInterval(() => {
            void loadLiveCount();
        }, 30_000);

        return () => {
            cancelled = true;
            window.clearInterval(intervalId);
        };
    }, [managerId]);

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
                    <span className="flex items-center gap-2">
                        Feed
                        {liveCount > 1 ? (
                            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white">
                                {liveCount}
                            </span>
                        ) : null}
                        {liveCount === 1 ? (
                            <span className="text-[10px] text-red-600 animate-pulse" aria-hidden="true">
                                ●
                            </span>
                        ) : null}
                    </span>
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
                    to="/knowledge-base"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isKnowledgeBase
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <BookOpenText className="w-4.5 h-4.5 min-w-4.5" />
                    Knowledge Base
                </Link>

                <Link
                    to="/manager/assignments/new"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isAssignments
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <ClipboardList className="w-4.5 h-4.5 min-w-4.5" />
                    Assign Drill
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

                <Link
                    to="/reps/invite"
                    className={`mt-4 flex items-center gap-3 rounded-xl border px-3 py-2 text-sm transition-all duration-200 ${isInvite
                            ? "border-accent/15 bg-accent text-white font-semibold"
                            : "border-white/25 bg-white/45 text-ink hover:bg-white/70 font-semibold"
                        }`}
                >
                    <UserPlus className="w-4.5 h-4.5 min-w-4.5" />
                    Invite Rep
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
