import { filterOptions, type FilterKey } from '../../api/contracts';

export function validateQuery(params: URLSearchParams): string | null {
  const q = params.get('q') ?? '';
  if ([...q].length > 200 || q.trim().split(/\s+/u).filter(Boolean).length > 10) {
    return 'Use at most 200 characters and 10 search terms.';
  }
  for (const key of Object.keys(filterOptions) as FilterKey[]) {
    if (params.getAll(key).some(value => !(filterOptions[key] as readonly string[]).includes(value))) {
      return 'Choose a valid filter value.';
    }
  }
  for (const [key, fallback, min, max] of [['limit', 20, 1, 50], ['offset', 0, 0, 10000]] as const) {
    const raw = params.get(key) ?? String(fallback);
    if (!/^\d+$/.test(raw) || Number(raw) < min || Number(raw) > max) return 'Choose valid pagination values.';
  }
  const revision = params.get('catalogue_revision');
  if (revision !== null && (!/^\d+$/.test(revision) || !Number.isSafeInteger(Number(revision)))) return 'Invalid catalogue revision.';
  return null;
}

export function resetPage(params: URLSearchParams) {
  const next = new URLSearchParams(params);
  next.delete('offset');
  next.delete('catalogue_revision');
  next.delete('profile_revision');
  return next;
}

export function apiQuery(params: URLSearchParams) {
  const query = new URLSearchParams();
  for (const key of ['q', 'job_type', 'employment_time', 'work_arrangement', 'limit', 'offset', 'catalogue_revision']) {
    params.getAll(key).forEach(value => query.append(key, value));
  }
  return query;
}
