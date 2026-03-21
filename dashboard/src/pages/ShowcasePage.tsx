import { useParams } from "react-router-dom";
import { PerformancePanel } from "../components/PerformancePanel";
import { DocumentUploadZone } from "../components/DocumentUploadZone";
import { Mic } from "lucide-react";

export function ShowcasePage() {
  const { id } = useParams();

  if (id === "analytics") {
    const analytics = {
      overall_score: 92,
      assignment_count: 14,
      sessions_count: 128,
      average_score: 88,
      completion_rate: 0.94,
    };
    const repProgress = {
      session_count: 42,
      scored_session_count: 38,
      average_score: 89,
      latest_sessions: [
        { session_id: "ses_abc123", overall_score: 91 },
        { session_id: "ses_def456", overall_score: 87 },
        { session_id: "ses_ghi789", overall_score: 94 },
      ]
    };
    const actions = [
      { id: "1", action_type: "Reviewed Session ses_abc123", occurred_at: new Date().toISOString(), manager_id: "1" },
      { id: "2", action_type: "Assigned Objection Handling", occurred_at: new Date(Date.now() - 3600000).toISOString(), manager_id: "1" },
      { id: "3", action_type: "Updated Training Material", occurred_at: new Date(Date.now() - 7200000).toISOString(), manager_id: "1" },
    ];

    return (
      <div className="min-h-screen bg-gradient-to-br from-accent-soft/40 via-white/60 to-accent-soft/30 p-12 flex items-center justify-center">
        <div className="w-full max-w-6xl">
          <PerformancePanel analytics={analytics as any} repProgress={repProgress as any} actions={actions as any} />
        </div>
      </div>
    );
  }

  if (id === "upload") {
    return (
      <div className="min-h-screen bg-gradient-to-br from-accent-soft/40 via-white/60 to-accent-soft/30 p-12 flex items-center justify-center">
        <div className="w-full max-w-3xl">
          <DocumentUploadZone 
            onUpload={async () => {}} 
            uploadState="uploading" 
            uploadProgress={68} 
          />
        </div>
      </div>
    );
  }

  if (id === "practice") {
    return (
      <div className="min-h-screen bg-gradient-to-br from-accent-soft/40 via-white/60 to-accent-soft/30 p-12 flex items-center justify-center">
        <div className="w-full max-w-4xl bg-white/60 backdrop-blur-2xl border border-white/40 shadow-xl shadow-black/5 rounded-3xl p-8 relative overflow-hidden">
             <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-accent/10 flex items-center justify-center">
                    <Mic className="w-6 h-6 text-accent" />
                  </div>
                  <div>
                    <h2 className="text-xl font-display font-bold tracking-tight text-ink">Live Practice Session</h2>
                    <p className="text-sm text-muted">Scenario: Skeptical Executive</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="flex items-center gap-2 text-sm font-medium rounded-full px-4 py-2 bg-white/50 border border-white/30 text-green-700">
                    <span className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
                    Connected
                  </span>
                </div>
             </div>
             <div className="grid grid-cols-2 gap-6">
                <div className="bg-white/40 rounded-2xl p-6 border border-white/20">
                   <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-4">You (Sales Rep)</h3>
                   <div className="space-y-4">
                     <div className="bg-accent/10 rounded-xl p-4 border border-accent/20">
                        <p className="text-sm text-ink font-medium">"Hi, I noticed your team recently expanded into the enterprise sector. How are you handling the increased support volume?"</p>
                     </div>
                     <div className="bg-white/50 rounded-xl p-4 border border-white/30 italic text-muted text-sm flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-accent animate-pulse" /> Listening...
                     </div>
                   </div>
                </div>
                <div className="bg-white/40 rounded-2xl p-6 border border-white/20">
                   <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-4">AI Persona (CTO)</h3>
                   <div className="space-y-4">
                     <div className="bg-white/50 rounded-xl p-4 border border-white/30">
                        <p className="text-sm text-ink font-medium">"We've definitely felt the strain. We are trying to hire, but onboarding is slow. Why do you ask?"</p>
                     </div>
                   </div>
                </div>
             </div>
        </div>
      </div>
    );
  }

  return <div>Invalid Showcase ID</div>;
}
