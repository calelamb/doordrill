import type { FeedItem } from "../lib/types";

type Props = {
  items: FeedItem[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
};

export function FeedList({ items, activeSessionId, onSelect }: Props) {
  return (
    <div className="panel feed-panel">
      <h2>Manager Feed</h2>
      {items.length === 0 ? <p className="muted">No sessions yet.</p> : null}
      <ul className="feed-list">
        {items.map((item) => (
          <li key={item.session_id}>
            <button
              className={`feed-item ${activeSessionId === item.session_id ? "active" : ""}`}
              onClick={() => onSelect(item.session_id)}
            >
              <div className="feed-item-top">
                <span>Rep {item.rep_id.slice(0, 8)}</span>
                <span className="score">{item.overall_score ?? "--"}</span>
              </div>
              <div className="feed-item-meta">
                <span>{item.session_status}</span>
                <span>{item.manager_reviewed ? "reviewed" : "needs review"}</span>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
