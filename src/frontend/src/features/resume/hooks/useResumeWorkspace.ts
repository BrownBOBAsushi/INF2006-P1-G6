import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type {
  PrepareWarning,
  ProcessingTaskResponse,
  ResumeContent,
  ResumeProfileResponse,
} from '../api/contractTypes';
import { isApiError, isUnknownOutcome } from '../api/errors';
import type { ResumeApiPort } from '../api/resumeApi';
import { emptyDraft, draftFromContent, type ResumeDraft } from '../model/draft';
import { draftReducer, type DraftAction, type EntrySection } from '../model/draftReducer';
import type { KeyFactory } from '../model/idempotency';
import { ResumeSaveController, type SaveStatus } from '../model/saveController';
import { contentEquals, toResumeContent } from '../model/serialize';
import {
  prepareFailureMessage,
  validateUploadSelection,
  type UploadRejection,
} from '../model/uploadValidation';
import { validateDraft, type ValidationResult } from '../model/validation';

export type WorkspacePhase = 'LOADING' | 'NO_RESUME' | 'PROFILE' | 'REVIEW';

export interface UseResumeWorkspaceOptions {
  api: ResumeApiPort;
  /** Injected in tests so backoff waits do not take real seconds. */
  sleep?: (seconds: number) => Promise<void>;
  keyFactory?: KeyFactory;
  /** Invoked when the session ended; the shell (Xue E) owns re-authentication. */
  onAuthenticationRequired?: () => void;
}

export interface ResumeConflict {
  /** Undefined means the current version could not be loaded. */
  profile: ResumeProfileResponse | null | undefined;
  revision: number | null;
}

export interface ResumeWorkspaceState {
  conflict: ResumeConflict | null;
  phase: WorkspacePhase;
  loadError: string | null;
  profile: ResumeProfileResponse | null;
  draft: ResumeDraft;
  dispatchDraft: (action: DraftAction) => void;
  validation: ValidationResult;
  /** Unsaved changes exist relative to the saved profile. */
  isDirty: boolean;

  selectedFile: File | null;
  uploadRejection: UploadRejection | null;
  preparing: boolean;
  prepareWarnings: PrepareWarning[];
  processingTask: ProcessingTaskResponse | null;
  /** Transient, never saved, never embedded. */
  unassignedParagraphs: string[];

  saveStatus: SaveStatus;
  saving: boolean;
  /** Idempotency key currently held; exposed for diagnostics and tests. */
  pendingIdempotencyKey: string | null;

  actions: {
    reload: () => Promise<void>;
    refreshConflict: () => Promise<void>;
    resolveConflict: (choice: 'KEEP_DRAFT' | 'USE_CURRENT') => void;
    selectFiles: (files: readonly File[]) => void;
    clearSelection: () => void;
    prepare: () => Promise<void>;
    startManualEntry: () => void;
    editSavedProfile: () => void;
    cancelReview: () => Promise<void>;
    assignParagraph: (index: number, section: EntrySection) => void;
    dismissParagraph: (index: number) => void;
    confirmSave: () => Promise<void>;
    checkSaveStatus: () => Promise<void>;
    deleteProfile: () => Promise<void>;
  };
}

const IDLE: SaveStatus = { kind: 'IDLE' };

export function useResumeWorkspace(options: UseResumeWorkspaceOptions): ResumeWorkspaceState {
  const { api, sleep, keyFactory, onAuthenticationRequired } = options;

  const [conflict, setConflict] = useState<ResumeConflict | null>(null);
  const [phase, setPhase] = useState<WorkspacePhase>('LOADING');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [profile, setProfile] = useState<ResumeProfileResponse | null>(null);
  const profileRef = useRef(profile);
  profileRef.current = profile;
  const [draft, dispatchDraft] = useReducer(draftReducer, undefined, emptyDraft);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadRejection, setUploadRejection] = useState<UploadRejection | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [prepareWarnings, setPrepareWarnings] = useState<PrepareWarning[]>([]);
  const [processingTask, setProcessingTask] = useState<ProcessingTaskResponse | null>(null);
  const [paragraphs, setParagraphs] = useState<string[]>([]);
  const [sourceExtractionTaskId, setSourceExtractionTaskId] = useState<string | null>(null);
  const taskEpoch = useRef(0);

  const [saveStatus, setSaveStatus] = useState<SaveStatus>(IDLE);
  const [saving, setSaving] = useState(false);
  const [keyTick, setKeyTick] = useState(0);

  const controller = useMemo(
    () =>
      new ResumeSaveController({
        api,
        ...(sleep ? { sleep } : {}),
        ...(keyFactory ? { keyFactory } : {}),
        onStatusChange: setSaveStatus,
      }),
    [api, sleep, keyFactory],
  );

  const authCallbackRef = useRef(onAuthenticationRequired);
  authCallbackRef.current = onAuthenticationRequired;

  const [expectedRevision, setExpectedRevision] = useState<number | null>(null);
  const validation = useMemo(
    () => {
      const result = validateDraft(draft, expectedRevision ?? 0);
      return { ...result, canSave: conflict === null && expectedRevision !== null && result.canSave };
    },
    [draft, expectedRevision, conflict],
  );

  const monitorExtraction = useCallback(async (taskId: string, epoch: number) => {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await (sleep ? sleep(1) : new Promise<void>((resolve) => setTimeout(resolve, 1000)));
      if (epoch !== taskEpoch.current) return;
      let task: ProcessingTaskResponse;
      try {
        task = await api.getProcessingTask(taskId);
      } catch (error) {
        if (isApiError(error) && (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED')) {
          taskEpoch.current += 1;
          authCallbackRef.current?.();
          setUploadRejection({ code: error.code, message: 'Sign in again to continue reviewing your resume.' });
        } else {
          setUploadRejection({ code: 'TASK_STATUS_UNAVAILABLE', message: 'Processing continues in the background. Reload to check its status.' });
        }
        setPreparing(false);
        return;
      }
      if (epoch !== taskEpoch.current) return;
      setProcessingTask(task);
      if (task.state === 'SUCCEEDED' && task.result !== null) {
        setSourceExtractionTaskId(task.task_id);
        dispatchDraft({ type: 'SET_CONTENT', content: task.result.draft });
        setParagraphs(task.result.unassigned_text.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean));
        setPrepareWarnings(task.result.warnings ?? []);
        setSaveStatus(IDLE);
        setPhase('REVIEW');
        setPreparing(false);
        return;
      }
      if (['FAILED', 'CANCELLED'].includes(task.state)) {
        setUploadRejection({ code: task.failure_code ?? 'PROCESSING_FAILED',
          message: task.failure_code === 'TEXT_REQUIRED'
            ? prepareFailureMessage('TEXT_REQUIRED')
            : 'The uploaded file could not be prepared. Your saved resume is unchanged; upload it again or enter details manually.' });
        setPreparing(false);
        return;
      }
    }
    if (epoch === taskEpoch.current) {
      setPreparing(false);
      setUploadRejection({ code: 'PROCESSING_CONTINUES', message: 'Processing continues in the background. Reload to check its status.' });
    }
  }, [api, sleep]);

  const isDirty = useMemo(() => {
    if (phase !== 'REVIEW') return false;
    const candidate = toResumeContent(draft);
    if (profile === null) {
      return !(
        candidate.skills.length === 0 &&
        candidate.projects.length === 0 &&
        candidate.experience.length === 0 &&
        candidate.education.length === 0
      );
    }
    return !contentEquals(candidate, profile.content);
  }, [phase, draft, profile]);

  const reload = useCallback(async () => {
    const epoch = ++taskEpoch.current;
    setPhase('LOADING');
    setLoadError(null);
    setExpectedRevision(null);
    try {
      const loaded = await api.getProfile();
      const revision = loaded?.revision ?? await api.getAccountRevision();
      let active: ProcessingTaskResponse | null = null;
      try {
        active = await api.getActiveExtraction();
      } catch (error) {
        if (isApiError(error) && (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED')) {
          authCallbackRef.current?.();
          throw error;
        }
        // Profile loading remains available when task status is temporarily unavailable.
        setUploadRejection({ code: 'TASK_STATUS_UNAVAILABLE', message: 'Your saved resume loaded, but processing status could not be checked. Reload to try again.' });
      }
      if (epoch !== taskEpoch.current) return;
      setExpectedRevision(revision);
      setConflict(null);
      setProfile(loaded);
      setProcessingTask(active);
      const result = active?.state === 'SUCCEEDED' ? active.result : null;
      if (active && result !== null && result !== undefined) {
        setSourceExtractionTaskId(active.task_id);
        dispatchDraft({ type: 'SET_CONTENT', content: result.draft });
        setParagraphs(result.unassigned_text.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean));
        setPrepareWarnings(result.warnings ?? []);
        setPhase('REVIEW');
      } else {
        setPhase(loaded === null ? 'NO_RESUME' : 'PROFILE');
        if (active && ['PENDING', 'PROCESSING', 'RETRY_WAIT'].includes(active.state)) {
          setPreparing(true);
          void monitorExtraction(active.task_id, epoch);
        }
      }
    } catch (error) {
      if (epoch !== taskEpoch.current) return;
      if (isApiError(error) && (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED')) {
        authCallbackRef.current?.();
        setLoadError('Your session ended. Sign in again to see your resume.');
      } else if (isUnknownOutcome(error)) {
        setLoadError('Your saved resume could not be loaded. Check your connection and try again.');
      } else {
        setLoadError('Your saved resume could not be loaded.');
      }
      setPhase('NO_RESUME');
    }
  }, [api, monitorExtraction]);

  useEffect(() => {
    void reload();
    return () => { taskEpoch.current += 1; };
  }, [reload]);

  useEffect(() => {
    if (profile?.embedding_state !== 'PENDING') return undefined;
    const revision = profile.revision;
    let stopped = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (stopped || attempts >= 30) return;
      attempts += 1;
      try {
        const current = await api.getProfile();
        if (stopped || profileRef.current?.revision !== revision) return;
        if (current === null || current.revision !== revision) return;
        setProfile(current);
        if (current.embedding_state === 'PENDING') timer = setTimeout(() => void poll(), 2000);
      } catch (error) {
        if (isApiError(error) && (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED')) {
          authCallbackRef.current?.();
        }
      }
    };
    timer = setTimeout(() => void poll(), 1000);
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [api, profile?.revision, profile?.embedding_state]);

  // PRD P07/P12: warn before losing an in-memory draft. Nothing is persisted.
  useEffect(() => {
    if (!isDirty) return undefined;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const selectFiles = useCallback((files: readonly File[]) => {
    taskEpoch.current += 1;
    const check = validateUploadSelection(files);
    if (check.ok) {
      setSelectedFile(check.file);
      setUploadRejection(null);
    } else {
      // Keep any previously accepted file; a bad drop should not discard a good choice.
      setUploadRejection(check.rejection);
    }
  }, []);

  const clearSelection = useCallback(() => {
    taskEpoch.current += 1;
    setSelectedFile(null);
    setUploadRejection(null);
  }, []);

  const prepare = useCallback(async () => {
    if (selectedFile === null || preparing || saving) return;
    const epoch = ++taskEpoch.current;
    setPreparing(true);
    setUploadRejection(null);
    try {
      const accepted = await api.prepare(selectedFile);
      if (epoch !== taskEpoch.current) return;
      await monitorExtraction(accepted.task_id, epoch);
    } catch (error) {
      if (epoch !== taskEpoch.current) return;
      if (isApiError(error)) {
        if (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED') {
          authCallbackRef.current?.();
        }
        // The file selection is deliberately retained, including on 503 PROCESSING_BUSY.
        setUploadRejection({ code: error.code, message: prepareFailureMessage(error.code) });
      } else {
        setUploadRejection({
          code: 'NO_RESPONSE',
          message: 'The upload did not complete. Your file is still selected — try again.',
        });
      }
    } finally {
      if (epoch === taskEpoch.current) setPreparing(false);
    }
  }, [api, selectedFile, preparing, saving, monitorExtraction]);

  const startManualEntry = useCallback(() => {
    if (preparing || saving) return;
    taskEpoch.current += 1;
    setSourceExtractionTaskId(null);
    dispatchDraft({ type: 'CLEAR' });
    setParagraphs([]);
    setPrepareWarnings([]);
    setSaveStatus(IDLE);
    setPhase('REVIEW');
  }, [preparing, saving]);

  const editSavedProfile = useCallback(() => {
    if (profile === null || preparing || saving) return;
    taskEpoch.current += 1;
    setSourceExtractionTaskId(null);
    dispatchDraft({ type: 'SET_CONTENT', content: profile.content });
    setParagraphs([]);
    setPrepareWarnings([]);
    setSaveStatus(IDLE);
    setPhase('REVIEW');
  }, [profile, preparing, saving]);

  const cancelReview = useCallback(async () => {
    const taskId = sourceExtractionTaskId ?? processingTask?.task_id ?? null;
    const epoch = ++taskEpoch.current;
    if (taskId !== null) {
      try {
        await api.discardExtraction(taskId);
      } catch (error) {
        if (epoch !== taskEpoch.current) return;
        if (isApiError(error) && (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED')) {
          authCallbackRef.current?.();
          return;
        }
        setUploadRejection({ code: 'TASK_DISCARD_FAILED', message: 'The reviewed draft could not be discarded on the server. Reload and try again.' });
        return;
      }
    }
    if (epoch !== taskEpoch.current) return;
    setSourceExtractionTaskId(null);
    setProcessingTask(null);
    dispatchDraft({ type: 'CLEAR' });
    setParagraphs([]);
    setPrepareWarnings([]);
    setSaveStatus(IDLE);
    setSelectedFile(null);
    controller.startNewAttempt();
    setKeyTick((t) => t + 1);
    setPhase(profile === null ? 'NO_RESUME' : 'PROFILE');
  }, [profile, controller, sourceExtractionTaskId, processingTask, api]);

  const assignParagraph = useCallback((index: number, section: EntrySection) => {
    setParagraphs((current) => {
      const text = current[index];
      if (text === undefined) return current;
      dispatchDraft({ type: 'ADD_ENTRY', section, description: text });
      return current.filter((_, i) => i !== index);
    });
  }, []);

  const dismissParagraph = useCallback((index: number) => {
    setParagraphs((current) => current.filter((_, i) => i !== index));
  }, []);

  const applyProfile = useCallback((next: ResumeProfileResponse | null | undefined) => {
    if (next === undefined) return;
    setProfile(next);
  }, []);

  const recordConflict = useCallback(async (current: ResumeProfileResponse | null | undefined) => {
    setConflict({ profile: current, revision: null });
    if (current === undefined) return;
    try {
      const revision = current?.revision ?? await api.getAccountRevision();
      setConflict({ profile: current, revision });
    } catch {
      setConflict({ profile: undefined, revision: null });
    }
  }, [api]);

  const refreshConflict = useCallback(async () => {
    try {
      await recordConflict(await api.getProfile());
    } catch {
      setConflict({ profile: undefined, revision: null });
    }
  }, [api, recordConflict]);

  const resolveConflict = useCallback((choice: 'KEEP_DRAFT' | 'USE_CURRENT') => {
    if (!conflict || conflict.revision === null || conflict.profile === undefined) return;
    setProfile(conflict.profile);
    setExpectedRevision(conflict.revision);
    if (choice === 'USE_CURRENT') {
      if (conflict.profile) dispatchDraft({ type: 'SET_CONTENT', content: conflict.profile.content });
      else dispatchDraft({ type: 'CLEAR' });
      setParagraphs([]);
    }
    // The reviewed text remains an intentional manual draft, but a source task
    // from the prior revision can no longer authorize saving it.
    setSourceExtractionTaskId(null);
    controller.startNewAttempt();
    setConflict(null);
    setSaveStatus(IDLE);
  }, [conflict, controller]);

  const confirmSave = useCallback(async () => {
    if (saving || conflict !== null || expectedRevision === null) return;
    const result = validateDraft(draft, expectedRevision);
    if (!result.canSave) {
      setSaveStatus({
        kind: 'FAILED',
        code: 'INVALID_CONTENT',
        message: 'Fix the highlighted fields before saving.',
        retryable: false,
      });
      return;
    }

    setSaving(true);
    try {
      const outcome = await controller.save(result.content, expectedRevision, sourceExtractionTaskId ?? undefined);
      if (outcome.status.kind === 'REVISION_CONFLICT') {
        await recordConflict(outcome.profile);
        return;
      }
      applyProfile(outcome.profile);

      switch (outcome.status.kind) {
        case 'SAVED': {
          if (outcome.profile === null) {
            setExpectedRevision(null);
            try {
              setExpectedRevision(await api.getAccountRevision());
            } catch {
              setLoadError('Your resume was deleted, but its current revision could not be loaded. Retry loading before saving again.');
            }
          } else {
            setExpectedRevision(outcome.profile?.revision ?? outcome.status.revision);
          }
          // When the controller already re-read the profile (possible replay), that
          // server content wins. Otherwise the submitted content is what committed.
          if (outcome.profile === undefined) {
            setProfile({
              revision: outcome.status.revision,
              content: result.content,
              embedding_version: profile?.embedding_version ?? '',
              has_matchable_resume: false,
              embedding_state: result.content.projects.length > 0 || result.content.experience.length > 0
                ? 'PENDING' : 'NOT_READY',
            });
          }
          setParagraphs([]);
          setSelectedFile(null);
          setSourceExtractionTaskId(null);
          setPhase(outcome.profile === null ? 'NO_RESUME' : 'PROFILE');
          break;
        }
        case 'REVIEW_REQUIRED': {
          // Replace the draft with the cleaned version and require another confirmation.
          dispatchDraft({ type: 'SET_CONTENT', content: outcome.status.cleanedContent });
          break;
        }
        case 'AUTH_REQUIRED': {
          authCallbackRef.current?.();
          break;
        }
        default:
          break;
      }
    } finally {
      setSaving(false);
      setKeyTick((t) => t + 1);
    }
  }, [saving, draft, expectedRevision, controller, applyProfile, profile, conflict, recordConflict, api, sourceExtractionTaskId]);

  const checkSaveStatus = useCallback(async () => {
    if (saving || conflict !== null) return;
    const operationId = controller.pendingKey;
    if (operationId === null) return;

    setSaving(true);
    try {
      const outcome = await controller.resolveOperation(operationId);
      if (outcome.status.kind === 'SAVED') {
        applyProfile(outcome.profile);
        if (outcome.profile === null) {
          setExpectedRevision(null);
          try {
            setExpectedRevision(await api.getAccountRevision());
          } catch {
            setLoadError('Your resume was deleted, but its current revision could not be loaded. Retry loading before saving again.');
          }
        } else {
          setExpectedRevision(outcome.profile?.revision ?? outcome.status.revision);
        }
        setParagraphs([]);
        setSelectedFile(null);
        setPhase(outcome.profile === null ? 'NO_RESUME' : 'PROFILE');
      } else if (outcome.profile !== undefined) {
        // An expired operation may include the current profile. Reconcile that
        // saved view while leaving the in-memory draft available for retry.
        applyProfile(outcome.profile);
        setExpectedRevision(outcome.profile?.revision ?? null);
      }
      if (outcome.status.kind === 'AUTH_REQUIRED') authCallbackRef.current?.();
    } finally {
      setSaving(false);
      setKeyTick((t) => t + 1);
    }
  }, [saving, conflict, controller, applyProfile, api]);

  const deleteProfile = useCallback(async () => {
    if (profile === null || saving || preparing) return;
    setSaving(true);
    try {
      const response = await api.deleteProfile(profile.revision);
      setProfile(null);
      setExpectedRevision(response.resume_revision);
      dispatchDraft({ type: 'CLEAR' });
      setParagraphs([]);
      setSelectedFile(null);
      setSourceExtractionTaskId(null);
      setSaveStatus({
        kind: 'DELETED',
        revision: response.resume_revision,
        message: `Your resume details were deleted. Your account and browsing are unaffected. (revision ${response.resume_revision})`,
      });
      setPhase('NO_RESUME');
    } catch (error) {
      if (isUnknownOutcome(error)) {
        setSaveStatus({
          kind: 'OUTCOME_UNKNOWN',
          reason: 'NO_RESPONSE',
          message:
            'We could not confirm whether your resume was deleted. Reload to see the current state.',
        });
      } else if (isApiError(error)) {
        if (error.code === 'AUTH_REQUIRED' || error.code === 'SESSION_EXPIRED') {
          authCallbackRef.current?.();
        }
        setSaveStatus({
          kind: 'FAILED',
          code: error.code,
          message: error.message,
          retryable: error.retryable,
        });
        if (error.code === 'REVISION_CONFLICT') await reload();
      }
    } finally {
      setSaving(false);
    }
  }, [api, profile, saving, preparing, reload]);

  // keyTick forces the exposed key to be re-read after a save settles.
  void keyTick;

  return {
    conflict,
    phase,
    loadError,
    profile,
    draft,
    dispatchDraft,
    validation,
    isDirty,
    selectedFile,
    uploadRejection,
    preparing,
    prepareWarnings,
    processingTask,
    unassignedParagraphs: paragraphs,
    saveStatus,
    saving,
    pendingIdempotencyKey: controller.pendingKey,
    actions: {
      reload,
      refreshConflict,
      resolveConflict,
      selectFiles,
      clearSelection,
      prepare,
      startManualEntry,
      editSavedProfile,
      cancelReview,
      assignParagraph,
      dismissParagraph,
      confirmSave,
      checkSaveStatus,
      deleteProfile,
    },
  };
}

/** Exposed for tests that need to build the same draft the hook would. */
export function draftForContent(content: ResumeContent): ResumeDraft {
  return draftFromContent(content);
}
