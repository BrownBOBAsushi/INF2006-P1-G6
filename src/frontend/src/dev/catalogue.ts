import type { JobDetail, JobPage, JobSummary, FilterKey } from '../api/contracts';
import { filterOptions } from '../api/contracts';
import { validateQuery } from '../features/catalogue/query';

/** Original synthetic fixtures. No provider data, real company or resume. */
export const jobs: JobDetail[] = Array.from({ length: 25 }, (_, index) => ({
  job_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  title: index === 0 ? 'Python Platform Intern' : index === 1 ? 'C++ Research Intern' : `Software Intern ${index + 1}`,
  company_name: index % 2 ? 'Synthetic Orchard Studio' : 'Synthetic Harbour Lab',
  country_code: 'SG', location: 'Singapore', job_type: index === 23 ? 'UNKNOWN' : 'INTERNSHIP',
  employment_time: index % 3 ? 'FULL_TIME' : 'PART_TIME',
  work_arrangement: index === 22 ? 'UNKNOWN' : index % 2 ? 'HYBRID' : 'REMOTE',
  posted_at: index === 23 ? null : `2026-09-${String(12 - index % 10).padStart(2, '0')}T00:00:00Z`,
  last_imported_at: '2026-09-12T00:00:00Z', is_active: index !== 24,
  description: index === 1 ? 'Explore C++ systems with 100% test coverage and literal_data paths. Use Python or JavaScript.' : 'Build Python APIs and SQL reports. Use Python or JavaScript. Learn testing with a mentor.',
  apply_url: 'https://example.com/synthetic-application', source: 'SYNTHETIC',
  source_url: 'https://example.com/synthetic-source', last_verified_at: null,
  eligibility_notes: [{ text: 'Currently enrolled students may apply.', source_quote: 'Currently enrolled students may apply.' }],
  requirements: [{ requirement_id: `10000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
    requirement_text: 'Use Python or JavaScript.', importance: 'REQUIRED',
    alternatives: ['Use Python.', 'Use JavaScript.'], source_quote: 'Use Python or JavaScript.' }],
}));

export function cataloguePage(params: URLSearchParams, revision = 1): JobPage {
  if (validateQuery(params)) throw new Error('INVALID_CONTENT');
  if (params.has('catalogue_revision') && Number(params.get('catalogue_revision')) !== revision) throw new Error('RESULTS_CHANGED');
  const terms = (params.get('q') ?? '').trim().toLocaleLowerCase('en').split(/\s+/u).filter(Boolean);
  const filtered = jobs.filter(job => job.is_active &&
    terms.every(term => `${job.title} ${job.company_name} ${job.description}`.toLocaleLowerCase('en').includes(term)) &&
    (Object.keys(filterOptions) as FilterKey[]).every(key => !params.has(key) || params.getAll(key).includes(job[key])));
  filtered.sort((a, b) => (b.posted_at ?? '').localeCompare(a.posted_at ?? '') || a.job_id.localeCompare(b.job_id));
  const limit = Number(params.get('limit') ?? 20), offset = Number(params.get('offset') ?? 0);
  const items: JobSummary[] = filtered.slice(offset, offset + limit).map(job => ({
    job_id: job.job_id, title: job.title, company_name: job.company_name, country_code: job.country_code,
    location: job.location, job_type: job.job_type, employment_time: job.employment_time,
    work_arrangement: job.work_arrangement, posted_at: job.posted_at, last_imported_at: job.last_imported_at, is_active: job.is_active,
  }));
  return { items, total: filtered.length, limit, offset, catalogue_revision: revision };
}
