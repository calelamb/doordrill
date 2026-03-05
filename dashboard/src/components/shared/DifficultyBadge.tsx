interface DifficultyBadgeProps {
    level: 1 | 2 | 3 | 4 | 5;
}

export function DifficultyBadge({ level }: DifficultyBadgeProps) {
    return (
        <div className="flex items-center gap-1">
            {[1, 2, 3, 4, 5].map((dot) => (
                <div
                    key={dot}
                    className={`w-2 h-2 rounded-full ${dot <= level ? 'bg-accent' : 'bg-accent-soft/60'
                        }`}
                />
            ))}
        </div>
    );
}
