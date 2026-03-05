import { LayoutDashboard, BarChart2, History, LogOut, TreePine } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

export function Sidebar() {
    const location = useLocation();

    // Determine active state manually (exact match for simplicity here)
    const isFeed = location.pathname.startsWith("/manager/feed");
    const isAnalytics = location.pathname.startsWith("/manager/analytics");
    const isActions = location.pathname.startsWith("/manager/actions");

    // Mocked state for the unreviewed count badge per PRD
    const unreviewedCount = 3; // In a real app this would be derived from a global state/context

    return (
        <aside className="w-[220px] shrink-0 bg-white/30 backdrop-blur-2xl border-r border-white/20 h-screen sticky top-0 flex flex-col">
            {/* Logo Area */}
            <div className="flex items-center gap-2.5 px-6 pt-6 pb-8">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-white shadow-lg shadow-accent/25">
                    <TreePine className="h-5 w-5" />
                </div>
                <span className="text-lg font-bold tracking-tight text-ink">DoorDrill</span>
            </div>

            {/* Nav Links */}
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
                    {unreviewedCount > 0 && (
                        <span
                            className="bg-accent text-white text-[10px] font-bold tracking-wide rounded-full min-w-[18px] h-[18px] flex items-center justify-center ml-auto px-1.5"
                            style={{
                                animation: "scaleIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards", // equivalent to framer-motion scale
                            }}
                        >
                            {unreviewedCount}
                        </span>
                    )}
                </Link>

                <Link
                    to="/manager/analytics"
                    className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-sm ${isAnalytics
                            ? "bg-accent-soft text-accent font-semibold"
                            : "text-muted hover:bg-white/40 font-medium"
                        }`}
                >
                    <BarChart2 className="w-4.5 h-4.5 min-w-4.5" />
                    Analytics
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

            {/* User Footer */}
            <div className="p-4 mt-auto border-t border-white/20">
                <button className="w-full flex items-center gap-3 p-2 rounded-xl hover:bg-white/40 transition-colors text-left group">
                    <div className="w-8 h-8 rounded-full bg-accent text-white flex items-center justify-center text-xs font-bold shrink-0">
                        MG
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-bold text-ink truncate">Manager</div>
                    </div>
                    <LogOut className="w-4 h-4 text-muted group-hover:text-ink transition-colors" />
                </button>
            </div>

            {/* Inline scale animation for the badge */}
            <style>{`
        @keyframes scaleIn {
          from { transform: scale(0); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }
      `}</style>
        </aside>
    );
}
