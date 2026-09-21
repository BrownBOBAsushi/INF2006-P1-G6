import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { ApiClient } from '../../api/client';
import { jobs } from '../../dev/catalogue';
import { createMockFetch } from '../../dev/mockFetch';
import { Catalogue } from './Catalogue';
import { SEARCH_DOCK_PIN_KEY } from './SearchDock';

function Location() { return <output data-testid="location">{useLocation().search}</output>; }
async function setup(path = '/jobs', inert = false) {
  const fetcher = createMockFetch();
  await fetcher('/api/auth/google', { method: 'POST', headers: { 'X-CSRF-Token': 'synthetic-bootstrap-csrf' } });
  const request = vi.fn(fetcher), client = new ApiClient(request);
  const view = render(<MemoryRouter initialEntries={[path]}><div inert={inert}><Catalogue client={client} /><Location /></div></MemoryRouter>);
  await screen.findByText(/active opportunities/);
  return { ...view, request, user: userEvent.setup() };
}
beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

test('dropdowns preserve multiple values and reset offset/revision without discarding other groups', async () => {
  const { user } = await setup('/jobs?offset=20&catalogue_revision=1');
  await user.click(screen.getByRole('button', { name: /Work arrangement/ }));
  await user.click(screen.getByRole('checkbox', { name: 'remote' }));
  await user.click(screen.getByRole('checkbox', { name: 'hybrid' }));
  const query = new URLSearchParams(screen.getByTestId('location').textContent!);
  expect(query.getAll('work_arrangement')).toEqual(['REMOTE', 'HYBRID']);
  expect(query.has('offset')).toBe(false); expect(query.has('catalogue_revision')).toBe(false);
  await user.click(screen.getByRole('button', { name: /Employment time/ }));
  expect(screen.queryByRole('checkbox', { name: 'remote' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('checkbox', { name: 'part time' }));
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.getByText(/active opportunities/)).toHaveTextContent('8 active opportunities'));
  expect(screen.getByTestId('location')).toHaveTextContent('employment_time=PART_TIME');
  await user.click(screen.getByRole('button', { name: /Work arrangement/ }));
  await user.click(screen.getByRole('button', { name: 'All work arrangement' }));
  expect(screen.getByTestId('location')).not.toHaveTextContent('work_arrangement');
  expect(screen.getByTestId('location')).toHaveTextContent('employment_time=PART_TIME');
});

test('dropdown supports keyboard entry, checkbox selection, Escape, outside click and focus leaving', async () => {
  const { user } = await setup();
  const trigger = screen.getByRole('button', { name: /Work arrangement/ });
  trigger.focus(); await user.keyboard('{ArrowDown}');
  expect(screen.getByRole('checkbox', { name: 'on site' })).toHaveFocus();
  await user.keyboard(' '); expect(screen.getByRole('checkbox', { name: 'on site' })).toBeChecked();
  await user.keyboard('{Escape}'); expect(trigger).toHaveFocus(); expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await user.click(trigger); await user.click(screen.getByLabelText('Keywords')); expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await user.click(trigger); await user.tab({ shift: true }); expect(trigger).toHaveAttribute('aria-expanded', 'false');
});

test('slash focuses search, typing slash remains literal, Enter and suggestion chips use the real query', async () => {
  const { user } = await setup();
  await user.keyboard('/'); expect(screen.getByLabelText('Keywords')).toHaveFocus();
  await user.type(screen.getByLabelText('Keywords'), 'C++ 100%'); await user.keyboard('{Enter}');
  await screen.findByText('1 active opportunities');
  await user.type(screen.getByLabelText('Keywords'), '/'); expect(screen.getByLabelText('Keywords')).toHaveValue('C++ 100%/');
  await user.click(screen.getByRole('button', { name: 'Python' }));
  await screen.findByText('24 active opportunities'); expect(screen.getByTestId('location')).toHaveTextContent('q=Python');
  await user.click(screen.getByRole('button', { name: 'Reset filters' }));
  expect(screen.getByLabelText('Keywords')).toHaveValue(''); expect(screen.getByTestId('location')).toBeEmptyDOMElement();
});

test('pin preference survives remount and is the only stored value', async () => {
  const first = await setup();
  await first.user.click(screen.getByRole('button', { name: 'Unpin search dock' }));
  expect(window.localStorage.getItem(SEARCH_DOCK_PIN_KEY)).toBe('false');
  expect(window.localStorage.length).toBe(1); first.unmount();
  const next = await setup();
  expect(screen.getByRole('button', { name: 'Pin search dock' })).toHaveAttribute('aria-pressed', 'false');
  await next.user.click(screen.getByRole('button', { name: 'Pin search dock' }));
  expect(screen.getByRole('region', { name: 'Search and filter internships' })).toHaveAttribute('data-pinned', 'true');
});

test('pinning still works when browser storage is blocked', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Blocked'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked'); });
  const { user } = await setup();
  await user.click(screen.getByRole('button', { name: 'Unpin search dock' }));
  expect(screen.getByRole('button', { name: 'Pin search dock' })).toHaveAttribute('aria-pressed', 'false');
});

test('desktop card selection keeps the current query and exposes the selected job in the URL', async () => {
  const { user } = await setup('/jobs?q=Python');
  await user.click(screen.getByRole('link', { name: jobs[0]!.title }));
  const query = new URLSearchParams(screen.getByTestId('location').textContent!);
  expect(query.get('q')).toBe('Python');
  expect(query.get('selected')).toBe(jobs[0]!.job_id);
  expect(screen.getByRole('complementary', { name: 'Selected job' })).toBeInTheDocument();
});

test('desktop selection returns the detail pane to its top when the job changes', async () => {
  const { user } = await setup();
  const pane = screen.getByRole('complementary', { name: 'Selected job' });
  pane.scrollTop = 902;
  await user.click(screen.getByRole('link', { name: 'Software Intern 17' }));
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(jobs[16]!.job_id));
  expect(pane.scrollTop).toBe(0);
});

test('slash cannot move focus into an inert workspace during session recovery', async () => {
  const { user } = await setup('/jobs', true);
  await user.keyboard('/');
  expect(screen.getByLabelText('Keywords')).not.toHaveFocus();
});

test('empty results expose a reset without fake recommendations', async () => {
  const { user } = await setup('/jobs?q=unfindable');
  expect(await screen.findByRole('heading', { name: 'No jobs found' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Clear search and filters' }));
  await screen.findByText('24 active opportunities');
  expect(within(screen.getByRole('complementary')).queryByText(/%/)).not.toBeInTheDocument();
});
