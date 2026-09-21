import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { App } from './App';
import { ApiClient } from './api/client';
import { MockSignIn, createMockFetch } from './dev/mockFetch';
import { jobs } from './dev/catalogue';
import { Catalogue } from './features/catalogue/Catalogue';

function Location() { return <output data-testid="location">{useLocation().pathname + useLocation().search}</output>; }
function setup(path = '/jobs', fetcher = createMockFetch()) {
  const request = vi.fn(fetcher);
  const client = new ApiClient(request);
  render(<MemoryRouter initialEntries={[path]}><App client={client} mock SignInControl={MockSignIn} /><Location /></MemoryRouter>);
  return { client, request, user: userEvent.setup() };
}
async function enter(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Enter synthetic preview' }));
  await user.type(await screen.findByLabelText('Display name'), 'Synthetic Student');
  await user.click(screen.getByRole('button', { name: 'Skip for now' }));
  await screen.findByRole('heading', { name: 'Browse internships' });
}
test('bootstrap/exchange CSRF, optional resume skip, paging, filter reset and literal keyword search', async () => {
  const { user, request } = setup();
  await enter(user);
  expect(request.mock.calls.some(([path]) => String(path).startsWith('/api/resume'))).toBe(false);
  const exchange = request.mock.calls.find(([path]) => path === '/api/auth/google')!;
  expect(new Headers(exchange[1]?.headers).get('X-CSRF-Token')).toBe('synthetic-bootstrap-csrf');
  const patch = request.mock.calls.find(([path, init]) => path === '/api/me' && init?.method === 'PATCH')!;
  expect(new Headers(patch[1]?.headers).get('X-CSRF-Token')).toBe('synthetic-session-csrf');
  await screen.findByText('24 active opportunities');
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByText('Page 2');
  expect(screen.getByTestId('location')).toHaveTextContent('offset=20&catalogue_revision=1');
  await user.click(screen.getByRole('button', { name: /Work arrangement/ }));
  await user.click(screen.getByRole('checkbox', { name: 'remote' }));
  await screen.findByText('Page 1');
  expect(screen.getByTestId('location')).not.toHaveTextContent('offset');
  expect(screen.getByTestId('location')).not.toHaveTextContent('catalogue_revision');
  await user.click(screen.getByRole('button', { name: 'Reset filters' }));
  await user.type(screen.getByLabelText('Keywords'), 'C++ 100%');
  await user.click(screen.getByRole('button', { name: 'Search jobs' }));
  await screen.findByText('1 active opportunities');
  await user.click(screen.getByRole('link', { name: 'C++ Research Intern' }));
  const apply = await screen.findByRole('link', { name: 'Apply on source website' });
  expect(apply).toHaveAttribute('href', jobs[1]!.apply_url);
  expect(apply).toHaveAttribute('target', '_blank');
  expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
  expect(request.mock.calls.every(([path]) => !String(path).includes('example.com'))).toBe(true);
});
test('closed details remain visible with Apply disabled; unknown UUID is not found', async () => {
  const fetcher = createMockFetch();
  await fetcher('/api/auth/google', { method: 'POST', headers: { 'X-CSRF-Token': 'synthetic-bootstrap-csrf' } });
  await fetcher('/api/me', { method: 'PATCH', headers: { 'X-CSRF-Token': 'synthetic-session-csrf' }, body: JSON.stringify({ display_name: 'Synthetic Student' }) });
  const { user } = setup('/jobs/' + jobs[24]!.job_id, fetcher);
  await screen.findByText('This listing is closed. Its details remain available.');
  expect(screen.getByRole('button', { name: 'Apply unavailable' })).toBeDisabled();
  expect(screen.queryByRole('link', { name: 'Apply on source website' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Logout' }));
  await screen.findByRole('button', { name: 'Enter synthetic preview' });
});
test('unknown job detail is not found after authenticated session restoration', async () => {
  const fetcher = createMockFetch();
  await fetcher('/api/auth/google', { method: 'POST', headers: { 'X-CSRF-Token': 'synthetic-bootstrap-csrf' } });
  await fetcher('/api/me', { method: 'PATCH', headers: { 'X-CSRF-Token': 'synthetic-session-csrf' }, body: JSON.stringify({ display_name: 'Synthetic Student' }) });
  setup('/jobs/ffffffff-ffff-4fff-8fff-ffffffffffff', fetcher);
  expect(await screen.findByRole('heading', { name: 'Job not found.' })).toBeInTheDocument();
});
test('resume seam mounts existing Nasya workspace and logout clears private UI', async () => {
  const { user } = setup();
  await enter(user);
  await user.click(screen.getByRole('link', { name: 'Resume' }));
  expect(await screen.findByTestId('no-resume-state')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Logout' }));
  await screen.findByRole('button', { name: 'Enter synthetic preview' });
  expect(screen.queryByTestId('no-resume-state')).not.toBeInTheDocument();
  expect(window.localStorage.length).toBe(0); expect(window.sessionStorage.length).toBe(0);
});
test('RESULTS_CHANGED restarts paging with a visible notice', async () => {
  const fetcher = createMockFetch();
  await fetcher('/api/auth/google', { method: 'POST', headers: { 'X-CSRF-Token': 'synthetic-bootstrap-csrf' } });
  const client = new ApiClient(fetcher);
  render(<MemoryRouter initialEntries={['/jobs?offset=20&catalogue_revision=0']}><Catalogue client={client} /><Location /></MemoryRouter>);
  await screen.findByText('The catalogue changed. Results restarted from the first page.');
  await screen.findByText('Page 1');
  expect(screen.getByTestId('location')).toHaveTextContent('/jobs');
  expect(screen.getByTestId('location')).not.toHaveTextContent('offset');
});
test('late cancelled catalogue response cannot overwrite a new search', async () => {
  let resolveOld!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(path => String(path).includes('q=new')
    ? Promise.resolve(new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0, catalogue_revision: 1 })))
    : new Promise(resolve => { resolveOld = resolve; }));
  const client = new ApiClient(fetcher);
  render(<MemoryRouter><Catalogue client={client} /></MemoryRouter>);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Keywords'), 'new');
  await user.click(screen.getByRole('button', { name: 'Search jobs' }));
  await screen.findByText('No jobs found');
  resolveOld(new Response(JSON.stringify({ items: [jobs[0]], total: 1, limit: 20, offset: 0, catalogue_revision: 1 })));
  await waitFor(() => expect(screen.queryByText('Python Platform Intern')).not.toBeInTheDocument());
});

test('session expiry preserves the open resume draft through same-account reauthentication', async () => {
  const fixtureFetch = createMockFetch();
  let expireSave = true;
  const fetcher: typeof fetch = async (path, init) => {
    if (expireSave && path === '/api/resume' && init?.method === 'PUT') {
      return new Response(JSON.stringify({ error: { code: 'SESSION_EXPIRED', message: 'Session ended.', request_id: 'synthetic', retryable: false, details: {} } }), { status: 401 });
    }
    return fixtureFetch(path, init);
  };
  const { user } = setup('/jobs', fetcher);
  await enter(user);
  await user.click(screen.getByRole('link', { name: 'Resume' }));
  await user.click(await screen.findByRole('button', { name: 'Enter my details without a PDF' }));
  await user.click(screen.getByRole('button', { name: 'Add project' }));
  await user.type(screen.getByLabelText('Title'), 'Synthetic course project');
  await user.type(screen.getByLabelText('Description'), 'Built a Python API for a synthetic class exercise.');
  await user.click(screen.getByRole('button', { name: 'Confirm and save' }));
  await screen.findByRole('heading', { name: 'Your session ended' });
  expect(screen.getByLabelText('Title')).toHaveValue('Synthetic course project');
  expireSave = false;
  await user.click(screen.getByRole('button', { name: 'Enter synthetic preview' }));
  await waitFor(() => expect(screen.queryByRole('heading', { name: 'Your session ended' })).not.toBeInTheDocument());
  expect(screen.getByLabelText('Title')).toHaveValue('Synthetic course project');
  expect(screen.getByTestId('location')).toHaveTextContent('/resume');
});

async function startResumeDraft(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('link', { name: 'Resume' }));
  await user.click(await screen.findByRole('button', { name: 'Enter my details without a PDF' }));
  await user.click(screen.getByRole('button', { name: 'Add project' }));
  await user.type(screen.getByLabelText('Title'), 'Synthetic retained project');
  await user.type(screen.getByLabelText('Description'), 'A synthetic course exercise with Python.');
}
test('CSRF recovery keeps the draft, holds focus and never automatically resubmits a save', async () => {
  const fixtureFetch = createMockFetch();
  let saves = 0;
  const fetcher: typeof fetch = async (path, init) => {
    if (path === '/api/resume' && init?.method === 'PUT') {
      saves++;
      return new Response(JSON.stringify({ error: { code: 'CSRF_INVALID', message: 'Refresh session.', request_id: 'synthetic', retryable: false, details: {} } }), { status: 403 });
    }
    return fixtureFetch(path, init);
  };
  const { user } = setup('/jobs', fetcher);
  await enter(user); await startResumeDraft(user);
  await user.click(screen.getByRole('button', { name: 'Confirm and save' }));
  const dialog = await screen.findByRole('dialog', { name: 'Refresh your session' });
  expect(dialog).toHaveFocus();
  expect(screen.getByRole('banner')).toHaveAttribute('inert');
  expect(screen.getByLabelText('Title')).toHaveValue('Synthetic retained project');
  await user.click(screen.getByRole('button', { name: 'Retry connection' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByLabelText('Title')).toHaveValue('Synthetic retained project');
  expect(saves).toBe(1);
});
test('reconnecting to a different account removes the previous private draft', async () => {
  const fixtureFetch = createMockFetch();
  let changedAccount = false;
  const fetcher: typeof fetch = async (path, init) => {
    if (path === '/api/resume' && init?.method === 'PUT') {
      changedAccount = true;
      return new Response(JSON.stringify({ error: { code: 'CSRF_INVALID', message: 'Refresh session.', request_id: 'synthetic', retryable: false, details: {} } }), { status: 403 });
    }
    const response = await fixtureFetch(path, init);
    if (path === '/api/me' && init?.method === 'GET' && changedAccount) {
      const body = await response.json();
      body.user.user_id = '20000000-0000-4000-8000-000000000002';
      return new Response(JSON.stringify(body));
    }
    return response;
  };
  const { user } = setup('/jobs', fetcher);
  await enter(user); await startResumeDraft(user);
  await user.click(screen.getByRole('button', { name: 'Confirm and save' }));
  await screen.findByRole('dialog', { name: 'Refresh your session' });
  await user.click(screen.getByRole('button', { name: 'Retry connection' }));
  await screen.findByTestId('no-resume-state');
  expect(screen.queryByDisplayValue('Synthetic retained project')).not.toBeInTheDocument();
});
test('an expired catalogue request recovers in place after reconnecting', async () => {
  const fixtureFetch = createMockFetch();
  let expireCatalogue = false;
  const fetcher: typeof fetch = async (path, init) => {
    if (String(path).startsWith('/api/jobs?') && expireCatalogue) {
      expireCatalogue = false;
      return new Response('{"error":{"code":"SESSION_EXPIRED"}}', { status: 401 });
    }
    return fixtureFetch(path, init);
  };
  const { user } = setup('/jobs', fetcher);
  await enter(user);
  await screen.findByText('24 active opportunities');
  expireCatalogue = true;
  await user.type(screen.getByLabelText('Keywords'), 'Python');
  await user.click(screen.getByRole('button', { name: 'Search jobs' }));
  await screen.findByRole('dialog', { name: 'Your session ended' });
  await user.click(screen.getByRole('button', { name: 'Retry connection' }));
  await screen.findByText('24 active opportunities');
  expect(screen.getByTestId('location')).toHaveTextContent('/jobs');
});
