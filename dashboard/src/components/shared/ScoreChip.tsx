import { Star } from 'lucide-react';

interface ScoreChipProps {
  score: number | null;
  size?: 'sm' | 'md' | 'lg';
}

export function ScoreChip({ score, size = 'md' }: ScoreChipProps) {
  let bgClass = 'bg-white/40';
  let textClass = 'text-muted';

  if (score !== null) {
    if (score >= 8.0) {
      bgClass = 'bg-emerald-100';
      textClass = 'text-emerald-800';
    } else if (score >= 6.5) {
      bgClass = 'bg-amber-100';
      textClass = 'text-amber-800';
    } else if (score >= 5.0) {
      bgClass = 'bg-orange-100';
      textClass = 'text-orange-800';
    } else {
      bgClass = 'bg-red-100';
      textClass = 'text-red-800';
    }
  }

  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5 rounded-full',
    md: 'text-sm px-2.5 py-1 rounded-full',
    lg: 'text-2xl font-bold px-4 py-2 rounded-xl',
  };

  const showIcon = (size === 'sm' || size === 'md') && score !== null;

  return (
    <span
      className={`inline-flex items-center justify-center font-medium ${bgClass} ${textClass} ${sizeClasses[size]}`}
    >
      {showIcon && <Star className="w-3 h-3 justify-center mr-1" />}
      {score !== null ? score.toFixed(1) : '--'}
    </span>
  );
}
