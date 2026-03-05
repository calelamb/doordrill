import { LucideIcon, Loader2, Inbox, AlertCircle } from 'lucide-react';

interface EmptyStateProps {
    variant: 'empty' | 'loading' | 'error';
    message: string;
    onRetry?: () => void;
    icon?: LucideIcon;
}

export function EmptyState({
    variant,
    message,
    onRetry,
    icon: CustomIcon,
}: EmptyStateProps) {
    return (
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
            {variant === 'loading' && (
                <>
                    <Loader2 className="w-8 h-8 animate-spin text-muted" />
                    <p className="text-muted text-sm">{message}</p>
                </>
            )}

            {variant === 'empty' && (
                <>
                    {CustomIcon ? (
                        <CustomIcon className="w-8 h-8 text-muted/40" />
                    ) : (
                        <Inbox className="w-8 h-8 text-muted/40" />
                    )}
                    <p className="text-muted text-sm">{message}</p>
                </>
            )}

            {variant === 'error' && (
                <>
                    <AlertCircle className="w-8 h-8 text-error" />
                    <p className="text-error text-sm">{message}</p>
                    {onRetry && (
                        <button
                            onClick={onRetry}
                            className="bg-accent text-white rounded-xl px-4 py-2 text-sm mt-1 hover:bg-accent-hover transition-colors"
                        >
                            Try again
                        </button>
                    )}
                </>
            )}
        </div>
    );
}
