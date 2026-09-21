import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { ApiClient } from '../../api/client';
import type { JobDetail } from '../../api/contracts';
import { jobs } from '../../dev/catalogue';
import { JobDetails } from './JobDetails';

function mount(fetcher: typeof fetch, id = jobs[0]!.job_id) {
  return render(<MemoryRouter initialEntries={['/jobs/' + id]}><Routes><Route path="/jobs/:id" element={<JobDetails client={new ApiClient(fetcher)} />} /></Routes></MemoryRouter>);
}
function response(job: JobDetail): typeof fetch { return vi.fn(async () => new Response(JSON.stringify(job))); }

test('detail uses source data, preserves protected Apply and does not invent metadata or match scores', async () => {
  mount(response(jobs[0]!));
  expect(screen.getByRole('status')).toHaveTextContent('Loading job details');
  await screen.findByRole('heading', { name: jobs[0]!.title });
  const apply = screen.getByRole('link', { name: /Apply on source website/ });
  expect(apply).toHaveAttribute('href', jobs[0]!.apply_url);
  expect(apply).toHaveAttribute('target', '_blank');
  expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
  expect(apply).toHaveAttribute('referrerpolicy', 'no-referrer');
  const source = within(screen.getByRole('region', { name: 'Source and freshness' }));
  expect(source.getByText('Not verified')).toBeInTheDocument();
  expect(source.getByRole('link')).toHaveAttribute('href', jobs[0]!.source_url);
  expect(screen.getByText(/Alternatives \(any one\): Use Python. OR Use JavaScript./)).toBeInTheDocument();
  expect(screen.queryByText(/match score|89%|deadline|allowance|contract duration/i)).not.toBeInTheDocument();
});
test('closed jobs remain readable while Apply is disabled', async () => {
  mount(response(jobs[24]!));
  await screen.findByRole('heading', { name: jobs[24]!.title });
  expect(screen.getByRole('status')).toHaveTextContent('This listing is closed');
  expect(screen.getByRole('button', { name: 'Apply unavailable' })).toBeDisabled();
  expect(screen.queryByRole('link', { name: /Apply on source/ })).not.toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'About this internship' })).getByText(jobs[24]!.description)).toBeInTheDocument();
});
test('unsafe links and absent optional data cannot imply a verified listing', async () => {
  mount(response({ ...jobs[0]!, apply_url: 'javascript:alert(1)', source_url: 'http://example.com', posted_at: null, requirements: [], eligibility_notes: [] }));
  await screen.findByRole('heading', { name: jobs[0]!.title });
  expect(screen.getByRole('button', { name: 'Apply unavailable' })).toBeDisabled();
  expect(screen.queryByRole('link', { name: /SYNTHETIC/ })).not.toBeInTheDocument();
  expect(screen.getByText(/No separate requirements were supplied/)).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Eligibility notes' })).not.toBeInTheDocument();
  expect(screen.getAllByText('Unknown')).toHaveLength(2);
});
test('loading failure supports an explicit retry', async () => {
  const fetcher = vi.fn<typeof fetch>().mockRejectedValueOnce(new TypeError('Offline')).mockResolvedValueOnce(new Response(JSON.stringify(jobs[0])));
  mount(fetcher);
  const retry = await screen.findByRole('button', { name: 'Retry loading details' });
  await userEvent.click(retry);
  await screen.findByRole('heading', { name: jobs[0]!.title });
  expect(fetcher).toHaveBeenCalledTimes(2);
});
test('malformed job identifiers show not-found without requesting data', async () => {
  const fetcher = response(jobs[0]!);
  mount(fetcher, 'invalid');
  expect(await screen.findByRole('heading', { name: 'Job not found.' })).toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});
