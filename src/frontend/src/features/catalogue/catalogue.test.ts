import { cataloguePage, jobs } from '../../dev/catalogue';
import { resetPage, validateQuery } from './query';
import { safeExternalUrl } from './JobDetails';

test('keyword AND spans fields, is case insensitive, and does not stem', () => {
  expect(cataloguePage(new URLSearchParams({ q: 'PYTHON Harbour' })).items.length).toBeGreaterThan(0);
  expect(cataloguePage(new URLSearchParams({ q: 'Python impossible' })).total).toBe(0);
  expect(cataloguePage(new URLSearchParams({ q: 'Pythons' })).total).toBe(0);
});
test.each(['C++', '100%', 'literal_data'])('punctuation stays literal: %s', q => {
  expect(cataloguePage(new URLSearchParams({ q })).items.map(job => job.job_id)).toEqual([jobs[1]!.job_id]);
});
test('OR within a filter, AND between filters and unknown only when selected/unrestricted', () => {
  const query = new URLSearchParams('work_arrangement=REMOTE&work_arrangement=HYBRID&employment_time=PART_TIME&limit=50');
  const page = cataloguePage(query);
  expect(page.items.length).toBeGreaterThan(1);
  expect(page.items.every(job => ['REMOTE', 'HYBRID'].includes(job.work_arrangement) && job.employment_time === 'PART_TIME')).toBe(true);
  expect(new Set(page.items.map(job => job.work_arrangement)).size).toBe(2);
  expect(cataloguePage(new URLSearchParams('work_arrangement=UNKNOWN')).items.map(job => job.job_id)).toEqual([jobs[22]!.job_id]);
});
test('active only, posting date descending, ID tiebreak, null dates last and summaries only', () => {
  const page = cataloguePage(new URLSearchParams('limit=50'));
  expect(page.total).toBe(24);
  expect(page.items.at(-1)?.posted_at).toBeNull();
  expect(page.items.every(job => job.is_active && !('description' in job) && !('apply_url' in job))).toBe(true);
  const sorted = [...page.items].sort((a,b) => (b.posted_at ?? '').localeCompare(a.posted_at ?? '') || a.job_id.localeCompare(b.job_id));
  expect(page.items).toEqual(sorted);
});
test('pages carry revision; changed catalogue rejects and query changes reset offset/revision', () => {
  const first = cataloguePage(new URLSearchParams());
  const second = cataloguePage(new URLSearchParams('offset=20&catalogue_revision=1'));
  expect(second.items.length).toBe(4);
  expect(second.items.some(job => first.items.some(other => other.job_id === job.job_id))).toBe(false);
  expect(() => cataloguePage(new URLSearchParams('catalogue_revision=0'))).toThrow('RESULTS_CHANGED');
  const reset = resetPage(new URLSearchParams('offset=20&catalogue_revision=1&q=Python'));
  expect(reset.toString()).toBe('q=Python');
});
test.each(['limit=0', 'limit=51', 'offset=-1', 'offset=10001', 'offset=1.2', 'work_arrangement=INVALID', 'catalogue_revision=abc', 'q=' + 'x'.repeat(201), 'q=' + Array(11).fill('term').join('+')])('rejects invalid query %s', query => {
  expect(validateQuery(new URLSearchParams(query))).not.toBeNull();
});
test.each(['javascript:alert(1)', 'http://example.com', 'https://user:pass@example.com', 'broken'])('external URLs reject %s', url => {
  expect(safeExternalUrl(url)).toBeUndefined();
});
test('HTTPS source URLs are retained without resume query parameters', () => {
  expect(safeExternalUrl('https://example.com/apply?id=1')).toBe('https://example.com/apply?id=1');
});
