import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { ApiClient } from '../../api/client';
import { Matches } from './Matches';

const firstJob = {
  job_id: '00000000-0000-4000-8000-000000000001', title: 'Platform engineering intern',
  company_name: 'Harbour Lab', country_code: 'SG', location: 'Singapore', job_type: 'INTERNSHIP' as const,
  employment_time: 'FULL_TIME' as const, work_arrangement: 'HYBRID' as const,
  posted_at: null, last_imported_at: '2026-09-12T00:00:00Z', is_active: true,
};
const secondJob = { ...firstJob, job_id: '00000000-0000-4000-8000-000000000002', title: 'AI engineering intern', company_name: 'Northstar Labs' };
const makeItem = (job: typeof firstJob) => ({
  job,
  requirements: [{ requirement_id: '10000000-0000-4000-8000-000000000001',
    requirement_text: 'Build and test backend APIs', importance: 'REQUIRED' as const,
    closest_passage: { text: 'Built a FastAPI service with PostgreSQL and automated integration tests. ' + 'More project detail. '.repeat(16), section: 'PROJECT', entry_index: 0 },
    explicit_skill_evidence: ['Python'], named_skills_not_evidenced: ['Redis'],
  }],
  eligibility_notes: [{ text: 'Applicants must be currently enrolled.', source_quote: 'Applicants must be currently enrolled.' }],
});
const matchPage = { items: [makeItem(firstJob), makeItem(secondJob)], total: 21, limit: 20, offset: 0, catalogue_revision: 4, profile_revision: 2 };
const detail = (job: typeof firstJob) => ({ ...job, description: 'Build useful tools.\n\nWork with our engineering team.',
  apply_url: 'https://employer.example/apply', source: 'Company site', source_url: 'https://employer.example/role',
  last_verified_at: null, eligibility_notes: [{ text: 'Applicants must be currently enrolled.', source_quote: 'Applicants must be currently enrolled.' }],
  requirements: [{ requirement_id: '10000000-0000-4000-8000-000000000001', requirement_text: 'Build and test backend APIs', importance: 'REQUIRED' as const, alternatives: [], source_quote: 'Build and test backend APIs.' }],
});
function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }
function renderMatches(fetcher: typeof fetch, initial = '/matches', accessRevision = 0) {
  const client = new ApiClient(fetcher);
  return Object.assign(render(<MemoryRouter initialEntries={[initial]}><Matches client={client} accessRevision={accessRevision} /></MemoryRouter>), { client });
}
function requestPath(request: RequestInfo | URL) { return String(request); }

test('shows the approved Matches framing and selects the first returned job with its live details', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = requestPath(input);
    return response(path.startsWith('/api/matches') ? matchPage : detail(firstJob));
  });
  renderMatches(request);
  expect(await screen.findByRole('heading', { name: 'Find your next internship' })).toBeInTheDocument();
  expect(screen.getByText('Jobs are ranked by how closely their requirements match the meaning of your projects and experience.')).toBeInTheDocument();
  expect(await screen.findByRole('heading', { name: 'Platform engineering intern' })).toBeInTheDocument();
  expect(screen.getByText('21 jobs ranked by resume similarity')).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: /Original listing/ })).toHaveAttribute('href', 'https://employer.example/role');
  expect(await screen.findByRole('link', { name: /View application/ })).toHaveAttribute('href', 'https://employer.example/apply');
  expect(screen.queryByText(/%|fit score|probability/i)).not.toBeInTheDocument();
  expect(request.mock.calls.some(([input]) => requestPath(input) === '/api/jobs/' + firstJob.job_id)).toBe(true);
});

test('loads selected-job details on selection and presents evidence as expandable source text', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = requestPath(input);
    if (path.startsWith('/api/matches')) return response(matchPage);
    return response(detail(path.endsWith(secondJob.job_id) ? secondJob : firstJob));
  });
  const user = userEvent.setup();
  renderMatches(request);
  await screen.findByRole('heading', { name: 'Platform engineering intern' });
  await user.click(screen.getByRole('button', { name: /AI engineering intern/ }));
  expect(await screen.findByRole('heading', { name: 'AI engineering intern' })).toBeInTheDocument();
  expect(request.mock.calls.some(([input]) => requestPath(input) === '/api/jobs/' + secondJob.job_id)).toBe(true);
  const requirement = screen.getByRole('button', { name: /Build and test backend APIs/ });
  expect(requirement).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByText(/Python/)).toBeInTheDocument();
  expect(screen.getByText(/Redis/)).toBeInTheDocument();
  expect(requirement).toHaveAttribute('aria-expanded', 'true');
  await user.click(requirement);
  expect(requirement).toHaveAttribute('aria-expanded', 'false');
  await user.click(requirement);
  expect(requirement).toHaveAttribute('aria-expanded', 'true');
  await user.click(screen.getByRole('button', { name: 'Read full passage' }));
  expect(screen.getByText(/More project detail/)).toBeInTheDocument();
});

test('ignores a late detail response after another job is selected', async () => {
  let resolveFirst!: (value: Response) => void;
  const firstDetails = new Promise<Response>(resolve => { resolveFirst = resolve; });
  const request = vi.fn<typeof fetch>().mockImplementation(input => {
    const path = requestPath(input);
    if (path.startsWith('/api/matches')) return Promise.resolve(response(matchPage));
    if (path.endsWith(firstJob.job_id)) return firstDetails;
    return Promise.resolve(response(detail(secondJob)));
  });
  const user = userEvent.setup();
  renderMatches(request);
  await screen.findByRole('heading', { name: 'Platform engineering intern' });
  await waitFor(() => expect(request.mock.calls.some(([input]) => requestPath(input).endsWith(firstJob.job_id))).toBe(true));
  await user.click(screen.getByRole('button', { name: /AI engineering intern/ }));
  expect(await screen.findByRole('link', { name: /View application/ })).toHaveAttribute('href', 'https://employer.example/apply');
  resolveFirst(response(detail(firstJob)));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'AI engineering intern' })).toBeInTheDocument());
  expect(screen.getByRole('heading', { name: 'AI engineering intern' })).toBeInTheDocument();
});

test('drops account-bound detail data when the access revision changes', async () => {
  let resolveOld!: (value: Response) => void;
  const oldDetails = new Promise<Response>(resolve => { resolveOld = resolve; });
  let detailsRequests = 0;
  const currentDetail = { ...detail(firstJob), apply_url: 'https://current.example/apply' };
  const request = vi.fn<typeof fetch>().mockImplementation(input => {
    const path = requestPath(input);
    if (path.startsWith('/api/matches')) return Promise.resolve(response(matchPage));
    detailsRequests += 1;
    return detailsRequests === 1 ? oldDetails : Promise.resolve(response(currentDetail));
  });
  const view = renderMatches(request);
  await waitFor(() => expect(detailsRequests).toBe(1));
  view.rerender(<MemoryRouter initialEntries={['/matches']}><Matches client={view.client} accessRevision={1} /></MemoryRouter>);
  expect(await screen.findByRole('link', { name: /View application/ })).toHaveAttribute('href', 'https://current.example/apply');
  resolveOld(response(detail(firstJob)));
  await waitFor(() => expect(screen.getByRole('link', { name: /View application/ })).toHaveAttribute('href', 'https://current.example/apply'));
});

test('mobile selection opens details and Back restores the list focus and scroll position', async () => {
  const originalMatchMedia = window.matchMedia;
  const originalScrollTo = window.scrollTo;
  const originalScrollY = window.scrollY;
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn((media: string) => ({
    matches: media === '(max-width: 720px)', media, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })) });
  window.scrollTo = vi.fn();
  Object.defineProperty(window, 'scrollY', { configurable: true, value: 180 });
  const request = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = requestPath(input);
    return response(path.startsWith('/api/matches') ? matchPage : detail(path.endsWith(secondJob.job_id) ? secondJob : firstJob));
  });
  try {
    const user = userEvent.setup();
    const { container } = renderMatches(request);
    await screen.findByRole('button', { name: /Platform engineering intern/ });
    expect(container.querySelector('.matches-detail-column')).toHaveAttribute('hidden');
    const selected = screen.getByRole('button', { name: /AI engineering intern/ });
    await user.click(selected);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'AI engineering intern' })).toHaveFocus());
    const back = screen.getByRole('button', { name: /Back to results/ });
    await user.click(back);
    await waitFor(() => expect(selected).toHaveFocus());
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 180, behavior: 'auto' });
  } finally {
    if (originalMatchMedia) Object.defineProperty(window, 'matchMedia', { configurable: true, value: originalMatchMedia });
    else delete (window as unknown as { matchMedia?: unknown }).matchMedia;
    window.scrollTo = originalScrollTo;
    Object.defineProperty(window, 'scrollY', { configurable: true, value: originalScrollY });
  }
});

test('entering the mobile breakpoint after a desktop selection returns to the list', async () => {
  const originalMatchMedia = window.matchMedia;
  let isMobile = false;
  let notifyBreakpoint: (() => void) | null = null;
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn((media: string) => ({
    get matches() { return isMobile; }, media, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn((_type: string, listener: EventListener) => { notifyBreakpoint = () => listener(new Event('change')); }),
    removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })) });
  const request = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = requestPath(input);
    return response(path.startsWith('/api/matches') ? matchPage : detail(path.endsWith(secondJob.job_id) ? secondJob : firstJob));
  });
  try {
    const user = userEvent.setup();
    const { container } = renderMatches(request);
    await screen.findByRole('button', { name: /Platform engineering intern/ });
    await user.click(screen.getByRole('button', { name: /AI engineering intern/ }));
    expect(await screen.findByRole('heading', { name: 'AI engineering intern' })).toBeInTheDocument();
    isMobile = true;
    act(() => notifyBreakpoint?.());
    await waitFor(() => expect(container.querySelector('.matches-detail-column')).toHaveAttribute('hidden'));
    expect(container.querySelector('.matches-list-column')).not.toHaveAttribute('hidden');
  } finally {
    if (originalMatchMedia) Object.defineProperty(window, 'matchMedia', { configurable: true, value: originalMatchMedia });
    else delete (window as unknown as { matchMedia?: unknown }).matchMedia;
  }
});

test('filters and searches preserve existing query keys and reset pagination revisions', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async input => response(requestPath(input).startsWith('/api/matches') ? matchPage : detail(firstJob)));
  const user = userEvent.setup();
  renderMatches(request, '/matches?offset=20&catalogue_revision=4&profile_revision=2');
  await screen.findByRole('heading', { name: 'Find your next internship' });
  await user.click(screen.getByRole('button', { name: /Filters/ }));
  await user.click(screen.getByRole('checkbox', { name: /internship/i }));
  expect(await screen.findByRole('button', { name: /internship, remove filter/i })).toBeInTheDocument();
  await user.type(screen.getByRole('searchbox', { name: 'Search jobs' }), 'Python');
  await user.click(screen.getByRole('button', { name: 'Search' }));
  const matchRequest = request.mock.calls.map(([input]) => requestPath(input)).find(path => path.includes('q=Python'));
  expect(matchRequest).toContain('job_type=INTERNSHIP');
  expect(matchRequest).not.toContain('offset=20');
  expect(matchRequest).not.toContain('profile_revision=2');
});

test('clearing filters keeps the current search and resets page revisions', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async input => response(requestPath(input).startsWith('/api/matches') ? matchPage : detail(firstJob)));
  const user = userEvent.setup();
  renderMatches(request);
  await screen.findByRole('heading', { name: 'Find your next internship' });
  await user.click(screen.getByRole('button', { name: /Filters/ }));
  await user.click(screen.getByRole('checkbox', { name: /internship/i }));
  await user.type(screen.getByRole('searchbox', { name: 'Search jobs' }), 'Python');
  await user.click(screen.getByRole('button', { name: 'Search' }));
  await waitFor(() => expect(request.mock.calls.map(([input]) => requestPath(input)).some(path => path.includes('q=Python') && path.includes('job_type=INTERNSHIP'))).toBe(true));
  await user.click(screen.getByRole('button', { name: /Clear all filters/ }));
  await waitFor(() => {
    const paths = request.mock.calls.map(([input]) => requestPath(input));
    const clearedQuery = paths.reverse().find(path => path.startsWith('/api/matches?') && path.includes('q=Python'));
    expect(clearedQuery).toContain('q=Python');
    expect(clearedQuery).not.toContain('job_type=INTERNSHIP');
    expect(clearedQuery).not.toContain('offset=');
    expect(clearedQuery).not.toContain('profile_revision=');
  });
});

test('keeps pagination revision handling and truthful empty state', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = requestPath(input);
    if (path.startsWith('/api/jobs/')) return response(detail(firstJob));
    if (path.includes('offset=20')) return response({ error: { code: 'RESULTS_CHANGED', message: 'changed', details: {} } }, 409);
    return response(matchPage);
  });
  const user = userEvent.setup();
  renderMatches(request);
  await screen.findByRole('heading', { name: 'Platform engineering intern' });
  await user.click(screen.getByRole('button', { name: /Next/ }));
  expect(await screen.findByText('Recommendations restarted because the catalogue or resume changed.')).toBeInTheDocument();
});

test('shows an honest failure when live details are unavailable', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async input => response(requestPath(input).startsWith('/api/matches') ? matchPage : { error: { code: 'NOT_FOUND' } }, requestPath(input).startsWith('/api/matches') ? 200 : 404));
  renderMatches(request);
  expect(await screen.findByRole('alert')).toHaveTextContent('This listing is no longer available.');
  expect(screen.queryByRole('link', { name: /View application/ })).not.toBeInTheDocument();
});

test.each([
  ['RESUME_REQUIRED', 'Save your resume before viewing recommendations.'],
  ['INSUFFICIENT_RESUME_INFORMATION', 'Add a project or experience entry to get recommendations.'],
  ['MODEL_VERSION_UNAVAILABLE', 'Recommendations are temporarily unavailable.'],
] as const)('shows an honest state for %s', async (code, message) => {
  const request = vi.fn<typeof fetch>().mockResolvedValue(response({ error: { code, message, details: {} } }, code === 'MODEL_VERSION_UNAVAILABLE' ? 503 : 422));
  renderMatches(request);
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(screen.getByRole('button', { name: 'Retry recommendations' })).toBeInTheDocument();
});
