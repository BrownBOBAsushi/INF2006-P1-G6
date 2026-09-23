import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { ApiClient } from '../../api/client';
import { Matches } from './Matches';

const job = {
  job_id: '00000000-0000-4000-8000-000000000001',
  title: 'Platform engineering intern',
  company_name: 'Synthetic Harbour Lab',
  country_code: 'SG',
  location: 'Singapore',
  job_type: 'INTERNSHIP' as const,
  employment_time: 'FULL_TIME' as const,
  work_arrangement: 'HYBRID' as const,
  posted_at: '2026-09-12T00:00:00Z',
  last_imported_at: '2026-09-12T00:00:00Z',
  is_active: true,
};

const matchPage = {
  items: [{
    job,
    requirements: [{
      requirement_id: '10000000-0000-4000-8000-000000000001',
      requirement_text: 'Use Python or JavaScript.',
      importance: 'REQUIRED',
      closest_passage: { text: 'Built a Python API for coursework.', section: 'PROJECT', entry_index: 0 },
      explicit_skill_evidence: ['Python'],
      named_skills_not_evidenced: [],
    }],
    eligibility_notes: [{ text: 'Currently enrolled students may apply.', source_quote: 'Currently enrolled students may apply.' }],
  }],
  total: 21,
  limit: 20,
  offset: 0,
  catalogue_revision: 4,
  profile_revision: 2,
};

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function renderMatches(fetcher: typeof fetch) {
  const client = new ApiClient(fetcher);
  return render(<MemoryRouter initialEntries={['/matches']}><Matches client={client} /></MemoryRouter>);
}

test('renders server match evidence and sends revisions when paging or filtering', async () => {
  const request = vi.fn<typeof fetch>().mockResolvedValue(response(matchPage));
  const user = userEvent.setup();
  renderMatches(request);

  expect(await screen.findByRole('heading', { name: 'Recommendations' })).toBeInTheDocument();
  expect(screen.getByText('Built a Python API for coursework.')).toBeInTheDocument();
  expect(screen.getByText('Python')).toBeInTheDocument();
  expect(screen.getByText('Currently enrolled students may apply.')).toBeInTheDocument();
  expect(screen.queryByText(/%|score|probability/i)).not.toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: 'Next' }));
  expect(String(request.mock.calls.at(-1)?.[0])).toContain('catalogue_revision=4');
  expect(String(request.mock.calls.at(-1)?.[0])).toContain('profile_revision=2');
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

test('restarts from page one when the server reports stale recommendation revisions', async () => {
  const request = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(response(matchPage))
    .mockResolvedValueOnce(response({ error: { code: 'RESULTS_CHANGED', message: 'changed', details: {} } }, 409))
    .mockResolvedValueOnce(response({ ...matchPage, items: [] }));
  const user = userEvent.setup();
  renderMatches(request);
  await screen.findByRole('heading', { name: 'Recommendations' });
  await user.click(screen.getByRole('button', { name: 'Next' }));
  expect(await screen.findByText('Recommendations restarted because the catalogue or resume changed.')).toBeInTheDocument();
});
