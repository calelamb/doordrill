import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Check, ChevronRight, Search, AlertCircle, Loader2, X } from "lucide-react";

import { DifficultyBadge } from "../components/shared/DifficultyBadge";
import { EmptyState } from "../components/shared/EmptyState";
import { SkillChip } from "../components/shared/SkillChip";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { createManagerAssignment, fetchManagerTeam, fetchScenarios } from "../lib/api";
import type { ManagerTeamMember, ScenarioSummary } from "../lib/types";

export function AssignmentCreatePage() {
    const navigate = useNavigate();
    const auth = getValidStoredAuth();
    const managerId = auth?.user.id ?? "";

    const [step, setStep] = useState<1 | 2 | 3>(1);
    const [scenarioId, setScenarioId] = useState<string | null>(null);
    const [scenarioSearch, setScenarioSearch] = useState("");

    const [selectedReps, setSelectedReps] = useState<string[]>([]);
    const [repSearch, setRepSearch] = useState("");

    const [dueDate, setDueDate] = useState("");
    const [minScore, setMinScore] = useState("");
    const [maxAttempts, setMaxAttempts] = useState("2");

    const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
    const [reps, setReps] = useState<ManagerTeamMember[]>([]);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const loadData = useCallback(async () => {
        if (!managerId) return;
        setLoading(true);
        setError(null);
        try {
            const [scenarioData, repData] = await Promise.all([
                fetchScenarios(),
                fetchManagerTeam(managerId),
            ]);
            setScenarios(scenarioData);
            setReps(repData);
        } catch (err) {
            if (isAuthError(err)) {
                clearStoredAuth();
                navigate("/login", { replace: true });
                return;
            }
            setError(err instanceof Error ? err.message : "Failed to load assignment builder");
        } finally {
            setLoading(false);
        }
    }, [managerId, navigate]);

    useEffect(() => {
        void loadData();
    }, [loadData]);

    const filteredScenarios = useMemo(
        () => scenarios.filter((s) => s.name.toLowerCase().includes(scenarioSearch.toLowerCase())),
        [scenarioSearch, scenarios]
    );
    const filteredReps = useMemo(
        () => reps.filter((r) => r.name.toLowerCase().includes(repSearch.toLowerCase())),
        [repSearch, reps]
    );

    const handleToggleRep = (id: string) => {
        setSelectedReps(prev => prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id]);
    };

    const handleSelectAllReps = () => {
        if (selectedReps.length === reps.length) {
            setSelectedReps([]);
        } else {
            setSelectedReps(reps.map(r => r.id));
        }
    };

    const handleSubmit = async () => {
        if (!managerId || !scenarioId || !selectedReps.length) {
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await Promise.all(selectedReps.map((repId) => createManagerAssignment(managerId, {
                scenario_id: scenarioId,
                rep_id: repId,
                due_at: dueDate ? new Date(`${dueDate}T23:59:59`).toISOString() : undefined,
                min_score_target: minScore ? Number(minScore) : undefined,
                retry_policy: { max_attempts: maxAttempts ? Number(maxAttempts) : 2 },
            })));
            window.dispatchEvent(new Event("manager-feed:refresh"));
            navigate("/manager/feed");
        } catch (err) {
            if (isAuthError(err)) {
                clearStoredAuth();
                navigate("/login", { replace: true });
                return;
            }
            setError(err instanceof Error ? err.message : "Failed to create assignment");
            setSubmitting(false);
        }
    };

    const selectedScenarioInfo = scenarios.find(s => s.id === scenarioId);
    const selectedRepsInfo = reps.filter(r => selectedReps.includes(r.id));

    if (loading) {
        return (
            <main className="max-w-4xl mx-auto px-6 py-8">
                <EmptyState variant="loading" message="Loading assignment builder..." />
            </main>
        );
    }

    return (
        <motion.main
            className="max-w-4xl mx-auto px-6 py-8 pb-32"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
        >
            <div className="mb-8">
                <h1 className="text-3xl font-bold tracking-tight text-ink">New Assignment</h1>
                <p className="mt-1 text-sm text-muted">Assign scenarios to reps</p>
            </div>

            {/* 8.1 Step Indicator */}
            <div className="flex items-center justify-between relative mb-12 max-w-2xl mx-auto">
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-1 bg-white/30 -z-10 rounded-full" />
                {/* Progress Fill */}
                <div
                    className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-accent -z-10 rounded-full transition-all duration-300"
                    style={{ width: step === 1 ? '0%' : step === 2 ? '50%' : '100%' }}
                />

                {[1, 2, 3].map((s) => {
                    const isCompleted = step > s;
                    const isActive = step === s;
                    const labels = ["Scenario", "Reps", "Confirm"];

                    return (
                        <div key={s} className="flex flex-col items-center gap-2">
                            <div
                                className={`w-10 h-10 rounded-full flex items-center justify-center font-bold transition-all duration-300 shadow-xl ${isActive ? "bg-accent text-white shadow-accent/25" :
                                        isCompleted ? "bg-accent-soft text-accent" :
                                            "bg-white text-muted border border-white/40"
                                    }`}
                            >
                                {isCompleted ? <Check className="w-5 h-5" /> : s}
                            </div>
                            <span className={`text-xs font-semibold ${isActive || isCompleted ? "text-ink" : "text-muted"}`}>
                                {labels[s - 1]}
                            </span>
                        </div>
                    )
                })}
            </div>

            <AnimatePresence mode="wait">
                {step === 1 && (
                    <motion.div
                        key="step1"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        className="space-y-6"
                    >
                        <div className="relative">
                            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted/50" />
                            <input
                                placeholder="Search scenarios..."
                                value={scenarioSearch}
                                onChange={e => setScenarioSearch(e.target.value)}
                                className="w-full bg-white/40 backdrop-blur-2xl border border-white/30 rounded-xl py-3.5 pl-12 pr-4 text-ink placeholder:text-muted/50 focus:ring-2 focus:ring-accent focus:border-accent outline-none shadow-sm transition-all text-sm"
                            />
                        </div>

                        <div className="flex flex-col gap-3">
                            {filteredScenarios.map(sc => {
                                const isSelected = sc.id === scenarioId;
                                const scenarioSkills = Object.keys(sc.rubric ?? {}).slice(0, 4).map((skill) => skill.replace(/_/g, " "));
                                return (
                                    <button
                                        key={sc.id}
                                        onClick={() => setScenarioId(sc.id)}
                                        className={`text-left p-5 rounded-xl transition-all duration-200 border ${isSelected
                                                ? "ring-2 ring-accent bg-accent-soft/30 border-accent/20 shadow-md shadow-accent/10"
                                                : "bg-white/30 backdrop-blur-xl border-white/20 hover:bg-white/50 hover:scale-[1.01]"
                                            }`}
                                    >
                                        <div className="flex justify-between items-start mb-2">
                                            <h3 className="font-medium text-ink">{sc.name}</h3>
                                            <DifficultyBadge level={sc.difficulty as 1 | 2 | 3 | 4 | 5} />
                                        </div>
                                        <p className="text-sm text-muted mb-4">{sc.description}</p>
                                        <div className="flex flex-wrap gap-2">
                                            {scenarioSkills.map(skill => (
                                                <SkillChip key={skill} label={skill} />
                                            ))}
                                        </div>
                                    </button>
                                )
                            })}
                            {filteredScenarios.length === 0 && (
                                <div className="py-12 text-center text-muted text-sm">No scenarios found.</div>
                            )}
                        </div>

                        {scenarioId && (
                            <motion.div
                                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                                className="fixed bottom-8 right-8"
                            >
                                <button
                                    onClick={() => setStep(2)}
                                    className="flex items-center gap-2 bg-accent text-white px-6 py-3.5 rounded-xl font-bold shadow-xl shadow-accent/30 hover:bg-accent-hover transition-all hover:scale-105"
                                >
                                    Next Step <ChevronRight className="w-5 h-5" />
                                </button>
                            </motion.div>
                        )}
                    </motion.div>
                )}

                {step === 2 && (
                    <motion.div
                        key="step2"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        className="space-y-6"
                    >
                        <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                            <div className="flex justify-between items-center mb-4">
                                <h3 className="font-semibold text-ink">Select Reps</h3>
                                <button
                                    onClick={handleSelectAllReps}
                                    className="text-accent text-sm font-medium hover:underline"
                                >
                                    {selectedReps.length === reps.length ? "Deselect All" : "Select All"}
                                </button>
                            </div>

                            {selectedReps.length > 0 && (
                                <div className="flex flex-wrap gap-2 mb-4 p-3 bg-white/30 rounded-xl border border-white/20">
                                    {selectedRepsInfo.map(r => (
                                        <span key={r.id} className="inline-flex items-center gap-1.5 bg-accent-soft text-accent rounded-full pl-3 pr-1 py-1 text-sm font-medium border border-accent/10">
                                            {r.name}
                                            <button onClick={() => handleToggleRep(r.id)} className="w-5 h-5 rounded-full hover:bg-black/10 flex items-center justify-center transition-colors">
                                                <X className="w-3.5 h-3.5" />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            )}

                            <div className="relative mb-4">
                                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted/50" />
                                <input
                                    placeholder="Filter reps..."
                                    value={repSearch}
                                    onChange={e => setRepSearch(e.target.value)}
                                    className="w-full bg-white/50 border border-white/40 rounded-lg py-2.5 pl-10 pr-4 text-ink placeholder:text-muted/50 focus:ring-2 focus:ring-accent outline-none shadow-sm text-sm"
                                />
                            </div>

                            <div className="space-y-2 max-h-[240px] overflow-y-auto thin-scrollbar pr-2">
                                {filteredReps.map(rep => (
                                    <label key={rep.id} className="flex items-center gap-3 p-3 bg-white/30 hover:bg-white/50 rounded-xl border border-transparent hover:border-white/40 cursor-pointer transition-all">
                                        <input
                                            type="checkbox"
                                            className="w-4 h-4 rounded border-white/40 text-accent focus:ring-accent"
                                            checked={selectedReps.includes(rep.id)}
                                            onChange={() => handleToggleRep(rep.id)}
                                        />
                                        <div className="w-8 h-8 rounded-full bg-accent-soft text-accent flex items-center justify-center text-xs font-bold">
                                            {rep.name.split(' ').map(n => n[0]).join('')}
                                        </div>
                                        <span className="font-medium text-sm text-ink">{rep.name}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 space-y-5">
                            <h3 className="font-semibold text-ink mb-1">Assignment Details <span className="text-muted font-normal text-sm ml-1">(Optional)</span></h3>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs font-semibold text-muted uppercase tracking-wide mb-1.5">Due Date</label>
                                    <input
                                        type="date"
                                        value={dueDate}
                                        onChange={e => setDueDate(e.target.value)}
                                        className="w-full bg-white/50 border border-white/40 rounded-xl py-2.5 px-3 text-sm text-ink focus:ring-2 focus:ring-accent outline-none"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-muted uppercase tracking-wide mb-1.5">Minimum Score (0-10)</label>
                                    <input
                                        type="number"
                                        min="0" max="10" step="0.5"
                                        value={minScore}
                                        onChange={e => setMinScore(e.target.value)}
                                        placeholder="e.g. 7.5"
                                        className="w-full bg-white/50 border border-white/40 rounded-xl py-2.5 px-3 text-sm text-ink focus:ring-2 focus:ring-accent outline-none"
                                    />
                                </div>
                            </div>

                            <div>
                                <label className="block text-xs font-semibold text-muted uppercase tracking-wide mb-1.5">Retry Attempts</label>
                                <input
                                    type="number"
                                    min="1"
                                    max="10"
                                    step="1"
                                    value={maxAttempts}
                                    onChange={e => setMaxAttempts(e.target.value)}
                                    className="w-full bg-white/50 border border-white/40 rounded-xl py-2.5 px-3 text-sm text-ink focus:ring-2 focus:ring-accent outline-none"
                                />
                            </div>
                        </div>

                        <div className="flex justify-between mt-8">
                            <button
                                onClick={() => setStep(1)}
                                className="px-6 py-3.5 rounded-xl font-medium text-muted hover:bg-white/30 transition-colors"
                            >
                                Back
                            </button>
                            {selectedReps.length > 0 && (
                                <button
                                    onClick={() => setStep(3)}
                                    className="flex items-center gap-2 bg-accent text-white px-6 py-3.5 rounded-xl font-bold shadow-xl shadow-accent/30 hover:bg-accent-hover transition-all hover:scale-105"
                                >
                                    Review Details <ChevronRight className="w-5 h-5" />
                                </button>
                            )}
                        </div>
                    </motion.div>
                )}

                {step === 3 && (
                    <motion.div
                        key="step3"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="space-y-6"
                    >
                        <AnimatePresence>
                            {error && (
                                <motion.div
                                    initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                                    className="flex items-center gap-3 bg-red-50 text-red-700 p-4 rounded-xl border border-red-200"
                                >
                                    <AlertCircle className="w-5 h-5 shrink-0" />
                                    <p className="text-sm font-medium">{error}</p>
                                </motion.div>
                            )}
                        </AnimatePresence>

                        <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                            <h3 className="font-semibold text-ink text-lg mb-6 border-b border-white/20 pb-4">Confirm Assignment</h3>

                            <div className="space-y-6">
                                <div>
                                    <span className="block text-xs font-semibold text-muted uppercase tracking-wide mb-2">Scenario</span>
                                    <div className="flex items-center gap-3 text-ink font-medium">
                                        {selectedScenarioInfo?.name}
                                        <DifficultyBadge level={selectedScenarioInfo?.difficulty as 1 | 2 | 3 | 4 | 5} />
                                    </div>
                                </div>

                                <div>
                                    <span className="block text-xs font-semibold text-muted uppercase tracking-wide mb-2">Assigned To ({selectedReps.length})</span>
                                    <div className="flex flex-wrap gap-2">
                                        {selectedRepsInfo.map(r => (
                                            <div key={r.id} className="flex items-center gap-2 bg-white/50 border border-white/40 rounded-full pr-3 pl-1 py-1">
                                                <div className="w-6 h-6 rounded-full bg-accent text-white flex items-center justify-center text-[10px] font-bold">
                                                    {r.name.split(' ').map(n => n[0]).join('')}
                                                </div>
                                                <span className="text-sm text-ink font-medium">{r.name}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                {(dueDate || minScore || maxAttempts) && (
                                    <div className="grid grid-cols-3 gap-4 border-t border-white/20 pt-4">
                                        {dueDate && (
                                            <div>
                                                <span className="block text-xs font-semibold text-muted uppercase tracking-wide mb-1">Due Date</span>
                                                <span className="text-sm text-ink font-medium">{new Date(dueDate).toLocaleDateString()}</span>
                                            </div>
                                        )}
                                        {minScore && (
                                            <div>
                                                <span className="block text-xs font-semibold text-muted uppercase tracking-wide mb-1">Min Score</span>
                                                <span className="text-sm text-ink font-medium bg-amber-100 text-amber-800 px-2 py-0.5 rounded-md">{minScore}</span>
                                            </div>
                                        )}
                                        <div>
                                            <span className="block text-xs font-semibold text-muted uppercase tracking-wide mb-1">Retry Attempts</span>
                                            <span className="text-sm text-ink font-medium">{maxAttempts || "2"}</span>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="flex justify-between items-center mt-8">
                            <button
                                onClick={() => setStep(2)}
                                disabled={submitting}
                                className="px-6 py-3.5 rounded-xl font-medium text-muted hover:bg-white/30 transition-colors disabled:opacity-50"
                            >
                                Back
                            </button>
                            <button
                                onClick={handleSubmit}
                                disabled={submitting}
                                className="flex items-center justify-center min-w-[200px] gap-2 bg-accent text-white px-8 py-4 rounded-xl font-bold shadow-xl shadow-accent/30 hover:bg-accent-hover transition-all hover:scale-105 disabled:opacity-70 disabled:hover:scale-100 disabled:cursor-wait"
                            >
                                {submitting ? (
                                    <><Loader2 className="w-5 h-5 animate-spin" /> Creating...</>
                                ) : (
                                    "Create Assignment"
                                )}
                            </button>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.main>
    );
}
