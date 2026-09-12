import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createResumeApi } from '../api/resumeApi';
import { createFakeTransport, jsonResponse, networkFailure } from '../fixtures/fakeTransport';
import { errorEnvelope, syntheticSavedProfile } from '../fixtures/resumeFixtures';
import { useResumeWorkspace } from '../hooks/useResumeWorkspace';

function workspace() {
  const transport = createFakeTransport();
  const api = createResumeApi(transport);
  const sleep = async () => {};
  return { transport, mount: () => renderHook(() => useResumeWorkspace({ api, sleep })) };
}

const absent = () => jsonResponse(404, errorEnvelope('RESUME_NOT_FOUND', 'No profile'));
const account = (revision: number) => jsonResponse(200, {
  user: { user_id: 'synthetic-user', display_name: null }, resume_revision: revision,
  has_resume: false, has_matchable_resume: false, csrf_token: 'synthetic-csrf',
});

describe('account revision survives profile deletion', () => {
  it('loads the account revision for an absent profile before saving', async () => {
    const { transport, mount } = workspace();
    transport.queue(absent(), account(8), jsonResponse(200, { operation_id: 'op', result_revision: 9, changed: true }));
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('NO_RESUME'));
    act(() => result.current.actions.startManualEntry());
    act(() => result.current.dispatchDraft({ type: 'ADD_SKILL', value: 'Python' }));
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.find(r => r.method === 'PUT')?.json).toMatchObject({ expected_revision: 8 });
    expect(result.current.profile?.revision).toBe(9);
  });

  it('uses the delete response revision for the next save', async () => {
    const { transport, mount } = workspace();
    transport.queue(jsonResponse(200, syntheticSavedProfile), jsonResponse(200, { resume_revision: 5, has_resume: false }),
      jsonResponse(200, { operation_id: 'op', result_revision: 6, changed: true }));
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('PROFILE'));
    await act(() => result.current.actions.deleteProfile());
    act(() => result.current.actions.startManualEntry());
    act(() => result.current.dispatchDraft({ type: 'ADD_SKILL', value: 'Python' }));
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.find(r => r.method === 'PUT')?.json).toMatchObject({ expected_revision: 5 });
    expect(result.current.profile?.revision).toBe(6);
  });

  it('does not guess revision zero when the account read fails', async () => {
    const { transport, mount } = workspace();
    transport.queue(absent(), networkFailure());
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('NO_RESUME'));
    act(() => result.current.actions.startManualEntry());
    act(() => result.current.dispatchDraft({ type: 'ADD_SKILL', value: 'Python' }));
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.filter(r => r.method === 'PUT')).toHaveLength(0);
    expect(result.current.loadError).not.toBeNull();
  });
});

describe('conflict reconciliation', () => {
  it('blocks another save until the student reviews and explicitly keeps their draft', async () => {
    const { transport, mount } = workspace();
    const latest = { ...syntheticSavedProfile, revision: 7, content: { ...syntheticSavedProfile.content, skills: ['Java'] } };
    transport.queue(jsonResponse(200, syntheticSavedProfile),
      jsonResponse(409, errorEnvelope('REVISION_CONFLICT', 'Changed elsewhere')),
      jsonResponse(200, latest));
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('PROFILE'));
    act(() => result.current.actions.editSavedProfile());
    await act(() => result.current.actions.confirmSave());
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.filter(r => r.method === 'PUT')).toHaveLength(1);
    expect(result.current.conflict?.profile).toEqual(latest);
    act(() => result.current.actions.resolveConflict('KEEP_DRAFT'));
    transport.queue(jsonResponse(200, { operation_id: 'op', result_revision: 8, changed: true }));
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.filter(r => r.method === 'PUT')[1]?.json).toMatchObject({ expected_revision: 7, content: { skills: syntheticSavedProfile.content.skills } });
  });

  it('keeps saving blocked if the current version cannot be refreshed', async () => {
    const { transport, mount } = workspace();
    transport.queue(jsonResponse(200, syntheticSavedProfile), jsonResponse(409, errorEnvelope('REVISION_CONFLICT', 'Changed elsewhere')), networkFailure());
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('PROFILE'));
    act(() => result.current.actions.editSavedProfile());
    await act(() => result.current.actions.confirmSave());
    expect(result.current.validation.canSave).toBe(false);
    transport.queue(jsonResponse(200, { ...syntheticSavedProfile, revision: 7 }));
    await act(() => result.current.actions.refreshConflict());
    act(() => result.current.actions.resolveConflict('USE_CURRENT'));
    expect(result.current.validation.canSave).toBe(true);
  });
});

describe('replay UI uses current server state', () => {
  it('keeps the review draft when the successful replay cannot be refreshed', async () => {
    const { transport, mount } = workspace();
    transport.queue(jsonResponse(200, syntheticSavedProfile), networkFailure(),
      jsonResponse(200, { operation_id: 'op', result_revision: 5, changed: true }), networkFailure());
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('PROFILE'));
    act(() => result.current.actions.editSavedProfile());
    act(() => result.current.dispatchDraft({ type: 'ADD_SKILL', value: 'New skill' }));
    await act(() => result.current.actions.confirmSave());
    expect(result.current.phase).toBe('REVIEW');
    expect(result.current.saveStatus.kind).toBe('SAVED_REFRESH_REQUIRED');
    expect(result.current.profile?.content.skills).not.toContain('New skill');
    expect(result.current.draft.skills.map(s => s.value)).toContain('New skill');
  });

  it('shows the empty state if the replayed save has since been deleted', async () => {
    const { transport, mount } = workspace();
    transport.queue(jsonResponse(200, syntheticSavedProfile), networkFailure(),
      jsonResponse(200, { operation_id: 'op', result_revision: 5, changed: true }), absent(), account(6));
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('PROFILE'));
    act(() => result.current.actions.editSavedProfile());
    await act(() => result.current.actions.confirmSave());
    expect(result.current.phase).toBe('NO_RESUME');
    expect(result.current.profile).toBeNull();
    act(() => result.current.actions.startManualEntry());
    act(() => result.current.dispatchDraft({ type: 'ADD_SKILL', value: 'Python' }));
    transport.queue(jsonResponse(200, { operation_id: 'next', result_revision: 7, changed: true }));
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.filter(r => r.method === 'PUT').at(-1)?.json).toMatchObject({ expected_revision: 6 });
  });
});

describe('concurrent recreation between absent-profile and account reads', () => {
  it('blocks saving until the newly created profile has been loaded', async () => {
    const { transport, mount } = workspace();
    const recreated = { ...syntheticSavedProfile, revision: 9 };
    transport.queue(absent(), jsonResponse(200, {
      user: { user_id: 'synthetic-user', display_name: null }, resume_revision: 9,
      has_resume: true, has_matchable_resume: true, csrf_token: 'synthetic-csrf',
    }));
    const { result } = mount();
    await waitFor(() => expect(result.current.phase).toBe('NO_RESUME'));
    act(() => result.current.actions.startManualEntry());
    act(() => result.current.dispatchDraft({ type: 'ADD_SKILL', value: 'Unseen overwrite' }));
    expect(result.current.validation.canSave).toBe(false);
    await act(() => result.current.actions.confirmSave());
    expect(transport.requests.filter(r => r.method === 'PUT')).toHaveLength(0);
    transport.queue(jsonResponse(200, recreated));
    await act(() => result.current.actions.reload());
    expect(result.current.profile).toEqual(recreated);
  });
});
