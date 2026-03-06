export type DashboardPeriodKey = "7" | "30" | "90" | "custom";

type DateWindow = {
  start: Date;
  end: Date;
  startInput: string;
  endInput: string;
  spanDays: number;
};

type PeriodWindow = {
  current: DateWindow;
  previous: DateWindow;
};

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0, 0);
}

function endOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59, 999);
}

export function toDateInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function resolvePeriodWindow(
  period: DashboardPeriodKey,
  customStart?: string,
  customEnd?: string,
  now = new Date()
): PeriodWindow {
  const fallbackEnd = new Date(now);
  let currentStart = new Date(fallbackEnd.getTime() - 30 * DAY_MS);
  let currentEnd = fallbackEnd;

  if (period === "custom" && customStart && customEnd) {
    const parsedStart = startOfDay(new Date(customStart));
    const parsedEnd = endOfDay(new Date(customEnd));
    if (Number.isFinite(parsedStart.getTime()) && Number.isFinite(parsedEnd.getTime()) && parsedEnd >= parsedStart) {
      currentStart = parsedStart;
      currentEnd = parsedEnd;
    }
  } else {
    const days = Number.parseInt(period, 10);
    const resolvedDays = Number.isFinite(days) ? days : 30;
    currentStart = new Date(fallbackEnd.getTime() - resolvedDays * DAY_MS);
    currentEnd = fallbackEnd;
  }

  const spanMs = Math.max(DAY_MS, currentEnd.getTime() - currentStart.getTime());
  const previousEnd = new Date(currentStart.getTime() - 1000);
  const previousStart = new Date(previousEnd.getTime() - spanMs);

  return {
    current: {
      start: currentStart,
      end: currentEnd,
      startInput: toDateInputValue(currentStart),
      endInput: toDateInputValue(currentEnd),
      spanDays: Math.max(1, Math.round(spanMs / DAY_MS)),
    },
    previous: {
      start: previousStart,
      end: previousEnd,
      startInput: toDateInputValue(previousStart),
      endInput: toDateInputValue(previousEnd),
      spanDays: Math.max(1, Math.round(spanMs / DAY_MS)),
    },
  };
}
