import { LayoutDashboard } from "lucide-react";
import { Link } from "react-router-dom";

export function NotFoundPage() {
    return (
        <main className="max-w-7xl mx-auto flex flex-col items-center justify-center py-24 px-6 text-center">
            <h1 className="text-4xl font-black text-ink mb-4">404</h1>
            <p className="text-muted mb-8 max-w-sm">The page you're looking for doesn't exist or has been moved.</p>

            <Link
                to="/manager/feed"
                className="inline-flex items-center gap-2 bg-accent text-white px-6 py-3 rounded-xl font-bold shadow-lg shadow-accent/25 hover:bg-accent-hover transition-all"
            >
                <LayoutDashboard className="w-5 h-5" />
                Return to Dashboard
            </Link>
        </main>
    );
}
