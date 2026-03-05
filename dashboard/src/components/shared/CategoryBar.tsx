import { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronDown, ChevronUp } from 'lucide-react';

interface CategoryBarProps {
    label: string;
    score: number;
    weight?: string;
    showRationale?: boolean;
    rationale?: string;
}

export function CategoryBar({
    label,
    score,
    weight,
    showRationale,
    rationale,
}: CategoryBarProps) {
    const [isExpanded, setIsExpanded] = useState(false);
    const fillWidth = `${(score / 10) * 100}%`;

    return (
        <div className="w-full">
            <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-medium text-ink flex items-center gap-2">
                    {label}
                    {weight && (
                        <span className="text-xs font-normal text-muted bg-white/40 px-1.5 py-0.5 rounded">
                            {weight}
                        </span>
                    )}
                </span>
                <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">
                        {score.toFixed(1)}
                    </span>
                    {showRationale && rationale && (
                        <button
                            onClick={() => setIsExpanded(!isExpanded)}
                            className="text-muted hover:text-ink transition-colors focus:outline-none"
                            aria-expanded={isExpanded}
                            aria-label={isExpanded ? "Hide rationale" : "Show rationale"}
                        >
                            {isExpanded ? (
                                <ChevronUp className="w-4 h-4" />
                            ) : (
                                <ChevronDown className="w-4 h-4" />
                            )}
                        </button>
                    )}
                </div>
            </div>

            <div className="w-full h-2 bg-accent-soft rounded-full overflow-hidden">
                <motion.div
                    className="h-full bg-accent rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: fillWidth }}
                    transition={{ duration: 0.6, delay: 0.1, ease: 'easeOut' }}
                />
            </div>

            {showRationale && rationale && isExpanded && (
                <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="mt-2"
                >
                    <p className="text-muted text-sm italic">{rationale}</p>
                </motion.div>
            )}
        </div>
    );
}
