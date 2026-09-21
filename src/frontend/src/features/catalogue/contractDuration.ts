export interface ContractDuration { months: number; days: number; totalDays: number }
const DAY = 86_400_000;

function sourceDate(value: string | null | undefined): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const result = new Date(value + 'T00:00:00Z');
  return Number.isFinite(result.getTime()) && result.toISOString().slice(0, 10) === value ? result : null;
}

function anniversary(start: Date, months: number): number {
  const result = new Date(start.getTime());
  result.setUTCDate(1);
  result.setUTCMonth(result.getUTCMonth() + months);
  const endOfMonth = new Date(result.getTime());
  endOfMonth.setUTCMonth(endOfMonth.getUTCMonth() + 1, 0);
  result.setUTCDate(Math.min(start.getUTCDate(), endOfMonth.getUTCDate()));
  return result.getTime();
}

/**
 * Elapsed calendar duration, excluding the end date, using source YYYY-MM-DD dates.
 * Calendar months clamp to the last day of shorter months; UTC avoids DST drift.
 * Not wired to JobDetail until the API contract supplies actual start/end dates.
 */
export function calculateContractDuration(startValue: string | null | undefined, endValue: string | null | undefined): ContractDuration | null {
  const start = sourceDate(startValue), end = sourceDate(endValue);
  if (!start || !end || end < start) return null;
  let months = (end.getUTCFullYear() - start.getUTCFullYear()) * 12 + end.getUTCMonth() - start.getUTCMonth();
  if (anniversary(start, months) > end.getTime()) months -= 1;
  return { months, days: (end.getTime() - anniversary(start, months)) / DAY, totalDays: (end.getTime() - start.getTime()) / DAY };
}
