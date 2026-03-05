import type { FeedItem } from "../lib/types";
import { motion } from "framer-motion";
import { Users, Star, CheckCircle2 } from "lucide-react";

type Props = {
  items: FeedItem[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
};

export function FeedList({ items, activeSessionId, onSelect }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6"
    >
      <h2 className="text-lg font-bold tracking-tight text-ink mb-4 flex items-center gap-2">
        <Users className="w-5 h-5 text-accent" />
        Manager Feed
      </h2>

      {items.length === 0 ? (
        <p className="text-muted text-sm">No sessions yet.</p>
      ) : null}

      <ul className="flex flex-col gap-3">
        {items.map((item, index) => {
          const isActive = activeSessionId === item.session_id;
          const isReviewed = item.manager_reviewed;

          return (
            <motion.li
              key={item.session_id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: index * 0.04 }}
              className="list-none"
            >
              <button
                className={`w-full text-left rounded-xl p-4 transition-all duration-200 hover:scale-[1.02] border cursor-pointer ${
                  isActive
                    ? "ring-2 ring-accent bg-accent-soft/40 border-accent/30 shadow-md shadow-accent/10"
                    : "bg-white/30 backdrop-blur-xl border-white/20 hover:bg-white/50 hover:shadow-md hover:shadow-black/5"
                }`}
                onClick={() => onSelect(item.session_id)}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-ink flex items-center gap-1.5">
                    <Users className="w-3.5 h-3.5 text-muted" />
                    Rep {item.rep_id.slice(0, 8)}
                  </span>
                  <span className="bg-accent/10 text-accent font-semibold rounded-full px-2.5 py-0.5 text-xs flex items-center gap-1">
                    <Star className="w-3 h-3" />
                    {item.overall_score ?? "--"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted font-medium">{item.session_status}</span>
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`inline-block w-1.5 h-1.5 rounded-full ${
                        isReviewed ? "bg-green-500" : "bg-amber-500"
                      }`}
                    />
                    <span
                      className={`font-medium ${
                        isReviewed ? "text-green-700" : "text-amber-700"
                      }`}
                    >
                      {isReviewed ? "reviewed" : "needs review"}
                    </span>
                    {isReviewed && <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />}
                  </span>
                </div>
              </button>
            </motion.li>
          );
        })}
      </ul>
    </motion.div>
  );
}
