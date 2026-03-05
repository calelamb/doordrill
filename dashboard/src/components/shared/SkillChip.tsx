interface SkillChipProps {
    label: string;
    variant?: 'default' | 'weak';
}

export function SkillChip({ label, variant = 'default' }: SkillChipProps) {
    const baseClasses = 'rounded-full px-3 py-1 text-xs font-medium inline-flex items-center justify-center';
    const variantClasses =
        variant === 'weak'
            ? 'bg-red-50 text-red-700'
            : 'bg-accent-soft text-accent';

    return <span className={`${baseClasses} ${variantClasses}`}>{label}</span>;
}
