import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createResumeApi } from '../api/resumeApi';
import { ResumeWorkspace } from '../components/ResumeWorkspace';
import {
  createFakeTransport,
  jsonResponse,
  type FakeTransport,
} from '../fixtures/fakeTransport';
import {
  errorEnvelope,
  syntheticCleanedContent,
  syntheticPdfFile,
  syntheticPrepareResponse,
  syntheticSavedProfile,
  syntheticSkillsOnlyProfile,
} from '../fixtures/resumeFixtures';

let transport: FakeTransport;
let keyCounter: number;

function renderWorkspace() {
  keyCounter = 0;
  return render(
    <ResumeWorkspace
      api={createResumeApi(transport)}
      sleep={async () => {}}
      keyFactory={() => `key-${(keyCounter += 1)}`}
    />,
  );
}

const absentAccount = () => jsonResponse(200, {
  user: { user_id: 'synthetic-user', display_name: null }, resume_revision: 0,
  has_resume: false, has_matchable_resume: false, csrf_token: 'synthetic-csrf',
});

const noResume = () => jsonResponse(404, errorEnvelope('RESUME_NOT_FOUND', 'no profile'));

beforeEach(() => {
  transport = createFakeTransport();
});

describe('empty states', () => {
  it('shows the no-resume state and still offers browsing', async () => {
    transport.queue(noResume(), absentAccount());
    renderWorkspace();
    expect(await screen.findByTestId('no-resume-state')).toHaveTextContent(/browse every internship/i);
  });

  it('distinguishes a saved profile that cannot produce recommendations', async () => {
    transport.queue(jsonResponse(200, syntheticSkillsOnlyProfile));
    renderWorkspace();
    expect(await screen.findByTestId('no-chunks-state')).toHaveTextContent(
      /project or experience entry/i,
    );
  });

  it('shows a saved profile with its revision', async () => {
    transport.queue(jsonResponse(200, syntheticSavedProfile));
    renderWorkspace();
    expect(await screen.findByTestId('saved-profile')).toHaveTextContent('Revision 4');
    expect(screen.queryByTestId('no-chunks-state')).not.toBeInTheDocument();
  });
});

describe('upload', () => {
  it('rejects a non-PDF dropped onto the dropzone without contacting the server', async () => {
    // The file input carries accept="application/pdf,.pdf", so the OS picker already
    // filters other types. Drag-and-drop does not honour `accept`, which is the path
    // where the client-side check actually matters.
    transport.queue(noResume(), absentAccount());
    renderWorkspace();
    await screen.findByTestId('no-resume-state');

    const notPdf = syntheticPdfFile('notes.txt', 1024, 'text/plain');
    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [notPdf] } });

    expect(await screen.findByTestId('upload-error')).toHaveAttribute('data-code', 'PDF_REQUIRED');
    expect(transport.requests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('accepts a PDF dropped onto the dropzone', async () => {
    transport.queue(noResume(), absentAccount());
    renderWorkspace();
    await screen.findByTestId('no-resume-state');

    fireEvent.drop(screen.getByTestId('dropzone'), {
      dataTransfer: { files: [syntheticPdfFile()] },
    });

    expect(await screen.findByTestId('selected-file')).toHaveTextContent('synthetic-resume.pdf');
    expect(screen.queryByTestId('upload-error')).not.toBeInTheDocument();
  });

  it('prepares a PDF and shows the editable review screen', async () => {
    transport.queue(noResume(), absentAccount(), jsonResponse(200, syntheticPrepareResponse));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');

    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));

    expect(await screen.findByRole('heading', { name: /review your details/i })).toBeInTheDocument();
    expect(screen.getByLabelText('Skill 1')).toHaveValue('Python');
    expect(screen.getAllByTestId('projects-entry')).toHaveLength(1);
    // The multipart body must carry the file and nothing else.
    const post = transport.requests.find((r) => r.method === 'POST');
    expect(post?.path).toBe('/api/resume/prepare');
    expect(post?.formData?.get('file')).toBeInstanceOf(File);
  });

  it('keeps the selected file when preparation is rejected as busy', async () => {
    transport.queue(
      noResume(),
      absentAccount(),
      jsonResponse(503, errorEnvelope('PROCESSING_BUSY', 'busy', { retryable: true })),
    );
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');

    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));

    expect(await screen.findByTestId('upload-error')).toHaveAttribute(
      'data-code',
      'PROCESSING_BUSY',
    );
    // The student should not have to pick the file again.
    expect(screen.getByTestId('selected-file')).toHaveTextContent('synthetic-resume.pdf');
    expect(screen.getByRole('button', { name: /prepare for review/i })).toBeEnabled();
  });

  it('explains a scanned PDF without leaking parser detail', async () => {
    transport.queue(
      noResume(),
      absentAccount(),
      jsonResponse(422, errorEnvelope('TEXT_REQUIRED', 'no text layer found')),
    );
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');

    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));

    const error = await screen.findByTestId('upload-error');
    expect(error).toHaveTextContent(/scanned or image-only/i);
    expect(error).not.toHaveTextContent(/no text layer found/i);
  });
});

describe('unassigned cleaned text', () => {
  it('offers the unclassified paragraphs instead of dropping them', async () => {
    transport.queue(noResume(), absentAccount(), jsonResponse(200, syntheticPrepareResponse));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));

    const panel = await screen.findByTestId('unassigned-panel');
    expect(within(panel).getAllByTestId('unassigned-paragraph')).toHaveLength(2);
  });

  it('copies a paragraph into an experience entry and removes it from the panel', async () => {
    transport.queue(noResume(), absentAccount(), jsonResponse(200, syntheticPrepareResponse));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));

    const panel = await screen.findByTestId('unassigned-panel');
    const first = within(panel).getAllByTestId('unassigned-paragraph')[0] as HTMLElement;
    await user.click(within(first).getByRole('button', { name: /add as experience/i }));

    expect(screen.getAllByTestId('experience-entry')).toHaveLength(2);
    expect(within(screen.getByTestId('unassigned-panel')).getAllByTestId('unassigned-paragraph'))
      .toHaveLength(1);
  });

  it('never sends unassigned_text in the save body', async () => {
    transport.queue(
      noResume(),
      absentAccount(),
      jsonResponse(200, syntheticPrepareResponse),
      jsonResponse(200, { operation_id: 'op-1', result_revision: 1, changed: true }),
    );
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));
    await user.click(await screen.findByRole('button', { name: /confirm and save/i }));

    const put = transport.requests.find((r) => r.method === 'PUT');
    const body = JSON.stringify(put?.json);
    expect(body).not.toContain('unassigned');
    expect(body).not.toContain('hackathon');
    expect(Object.keys((put?.json as { content: object }).content).sort()).toEqual([
      'education',
      'experience',
      'projects',
      'skills',
    ]);
  });
});

describe('saving from the review screen', () => {
  it('returns to the saved profile view after a successful save', async () => {
    transport.queue(
      noResume(),
      absentAccount(),
      jsonResponse(200, syntheticPrepareResponse),
      jsonResponse(200, { operation_id: 'op-1', result_revision: 1, changed: true }),
    );
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));
    await user.click(await screen.findByRole('button', { name: /confirm and save/i }));

    expect(await screen.findByTestId('saved-profile')).toHaveTextContent('Revision 1');
    expect(screen.getByTestId('save-status')).toHaveTextContent(/resume saved/i);
  });

  it('installs the cleaned draft and waits for a second confirmation on REVIEW_REQUIRED', async () => {
    transport.queue(
      noResume(),
      absentAccount(),
      jsonResponse(200, syntheticPrepareResponse),
      jsonResponse(
        422,
        errorEnvelope('REVIEW_REQUIRED', 'privacy check changed your content', {
          details: { draft: syntheticCleanedContent },
        }),
      ),
    );
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));
    await user.click(await screen.findByRole('button', { name: /confirm and save/i }));

    // Still on the review screen, now showing the cleaned text.
    expect(screen.getByRole('heading', { name: /review your details/i })).toBeInTheDocument();
    expect(screen.getByTestId('save-status')).toHaveTextContent(/nothing has been saved yet/i);
    await waitFor(() => {
      const project = screen.getAllByTestId('projects-entry')[0] as HTMLElement;
      expect(within(project).getByLabelText(/^description$/i)).toHaveValue(
        syntheticCleanedContent.projects[0]?.description,
      );
    });
  });

  it('blocks saving when every field has been emptied', async () => {
    transport.queue(noResume(), absentAccount());
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.click(screen.getByRole('button', { name: /enter my details without a pdf/i }));

    const confirm = await screen.findByRole('button', { name: /confirm and save/i });
    expect(confirm).toBeDisabled();
    expect(screen.getByTestId('issues-content')).toHaveTextContent(/add at least one/i);
  });
});

describe('draft privacy', () => {
  it('never writes the draft to browser storage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    transport.queue(noResume(), absentAccount(), jsonResponse(200, syntheticPrepareResponse));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('no-resume-state');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    await user.click(await screen.findByRole('button', { name: /prepare for review/i }));
    await screen.findByRole('heading', { name: /review your details/i });

    await user.type(screen.getByLabelText('Skill 1'), 'x');
    expect(setItem).not.toHaveBeenCalled();
  });
});

describe('review safety during requests', () => {
  it('locks draft inputs while the submitted version is being saved', async () => {
    transport.queue(jsonResponse(200, syntheticSavedProfile));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('saved-profile');
    await user.click(screen.getByRole('button', { name: 'Edit details' }));
    let finish!: (value: import('../api/httpTransport').HttpResponse) => void;
    vi.spyOn(transport, 'send').mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await user.click(screen.getByRole('button', { name: /confirm and save/i }));
    expect(screen.getByLabelText('Skill 1')).toBeDisabled();
    expect(screen.getByRole('button', { name: /add skill/i })).toBeDisabled();
    finish({ status: 200, body: { operation_id: 'op', result_revision: 5, changed: true }, header: () => null });
    await screen.findByTestId('saved-profile');
  });

  it('blocks manual editing while PDF preparation is pending', async () => {
    transport.queue(jsonResponse(200, syntheticSavedProfile));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('saved-profile');
    await user.upload(screen.getByLabelText(/choose a pdf resume/i), syntheticPdfFile());
    let finish!: (value: import('../api/httpTransport').HttpResponse) => void;
    vi.spyOn(transport, 'send').mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await user.click(screen.getByRole('button', { name: /prepare for review/i }));
    expect(screen.getByRole('button', { name: /enter my details without a pdf/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit details' })).toBeDisabled();
    finish({ status: 200, body: syntheticPrepareResponse, header: () => null });
    await screen.findByRole('heading', { name: /review your details/i });
  });

  it('shows the fetched version and requires a choice after a conflict', async () => {
    transport.queue(jsonResponse(200, syntheticSavedProfile),
      jsonResponse(409, errorEnvelope('REVISION_CONFLICT', 'Changed elsewhere')),
      jsonResponse(200, { ...syntheticSavedProfile, revision: 7, content: { ...syntheticSavedProfile.content, skills: ['Java-only-in-other-tab'] } }));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByTestId('saved-profile');
    await user.click(screen.getByRole('button', { name: 'Edit details' }));
    await user.click(screen.getByRole('button', { name: /confirm and save/i }));
    expect(await screen.findByText('Java-only-in-other-tab')).toBeVisible();
    expect(screen.getByRole('button', { name: /confirm and save/i })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /discard my draft and use current version/i }));
    expect(screen.getByLabelText('Skill 1')).toHaveValue('Java-only-in-other-tab');
    expect(screen.getByRole('button', { name: /confirm and save/i })).toBeEnabled();
  });
});
