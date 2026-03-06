type ChartSkeletonProps = {
  className?: string;
  heightClass?: string;
};

export function ChartSkeleton({
  className = "",
  heightClass = "h-64",
}: ChartSkeletonProps) {
  return (
    <div
      className={`w-full animate-pulse rounded-2xl bg-white/30 backdrop-blur-md ${heightClass} ${className}`.trim()}
    />
  );
}
