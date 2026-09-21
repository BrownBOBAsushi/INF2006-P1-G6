export const label = (value: string) => value.toLowerCase().replaceAll('_', ' ');
export function displayDate(value: string | null): string {
  if (!value) return 'Unknown';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown' : new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
}
export function initials(value: string) {
  return value.trim().split(/\s+/).slice(0, 2).map(part => [...part][0]).join('').toUpperCase();
}
