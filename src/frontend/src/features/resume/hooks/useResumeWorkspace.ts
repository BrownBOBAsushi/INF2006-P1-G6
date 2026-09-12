import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type {
  PrepareWarning,
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

export interface ResumeWorkspaceState {
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
  /** Transient, never saved, never embedded. */
  unassignedParagraphs: string[];

  saveStatus: SaveStatus;
  saving: boolean;
  /** Idempotency key currently held; exposed for diagnostics and tests. */
  pendingIdempotencyKey: string | null;

  actions: {
    reload: () => Promise<void>;
    selectFiles: (files: readonly File[]) => void;
    clearSelection: () => void;
    prepare: () => Promise<void>;
    startManualEntry: () => void;
    editSavedProfile: () => void;
    cancelReview: () => void;
    assignParagraph: (index: number, section: EntrySection) => void;
    dismissParagraph: (index: number) => void;
    confirmSave: () => Promise<void>;
    deleteProfile: () => Promise<void>;
  };
}

const IDLE: SaveStatus = { kind: 'IDLE' };

export function useResumeWorkspace(options: UseResumeWorkspaceOptions): ResumeWorkspaceState {
  const { api, sleep, keyFactory, onAuthenticationRequired } = options;

  const [phase, setPhase] = useState<WorkspacePhase>('LOADING');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [profile, setProfile] = useState<ResumeProfileResponse | null>(null);
  const [draft, dispatchDraft] = useReducer(draftReducer, undefined, emptyDraft);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadRejection, setUploadRejection] = useState<UploadRejection | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [prepareWarnings, setPrepareWarnings] = useState<PrepareWarning[]>([]);
  const [paragraphs, setParagraphs] = useState<string[]>([]);

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

  const expectedRevision = profile?.revision ?? 0;
  const validation = useMemo(
    () => validateDraft(draft, expectedRevision),
    [draft, expectedRevision],
  );

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
    setPhase('LOADING');
    setLoadError(null);
    try {
      const loaded = await api.getProfile();
      setProfile(loaded);
      setPhase(loaded === null ? 'NO_RESUME' : 'PROFILE');
    } catch (error) {
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
  }, [api]);

  useEffect(() => {
    void reload();
  }, [reload]);

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
    setSelectedFile(null);
    setUploadRejection(null);
  }, []);

  const prepare = useCallback(async () => {
    if (selectedFile === null || preparing) return;
    setPreparing(true);
    setUploadRejection(null);
    try {
      const response = await api.prepare(selectedFile);
      dispatchDraft({ type: 'SET_CONTENT', content: response.draft });
      setParagraphs(
        response.unassigned_text
          .split(/\n\s*\n/)
          .map((p) => p.trim())
          .filter((p) => p.length > 0),
      );
      setPrepareWarnings(response.warnings ?? []);
      setSaveStatus(IDLE);
      setPhase('REVIEW');
    } catch (error) {
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
      setPreparing(false);
    }
  }, [api, selectedFile, preparing]);

  const startManualEntry = useCallback(() => {
    dispatchDraft({ type: 'CLEAR' });
    setParagraphs([]);
    setPrepareWarnings([]);
    setSaveStatus(IDLE);
    setPhase('REVIEW');
  }, []);

  const editSavedProfile = useCallback(() => {
    if (profile === null) return;
    dispatchDraft({ type: 'SET_CONTENT', content: profile.content });
    setParagraphs([]);
    setPrepareWarnings([]);
    setSaveStatus(IDLE);
    setPhase('REVIEW');
  }, [profile]);

  const cancelReview = useCallback(() => {
    dispatchDraft({ type: 'CLEAR' });
    setParagraphs([]);
    setPrepareWarnings([]);
    setSaveStatus(IDLE);
    setSelectedFile(null);
    controller.startNewAttempt();
    setKeyTick((t) => t + 1);
    setPhase(profile === null ? 'NO_RESUME' : 'PROFILE');
  }, [profile, controller]);

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

  const confirmSave = useCallback(async () => {
    if (saving) return;
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
      const outcome = await controller.save(result.content, expectedRevision);
      applyProfile(outcome.profile);

      switch (outcome.status.kind) {
        case 'SAVED': {
          // When the controller already re-read the profile (possible replay), that
          // server content wins. Otherwise the submitted content is what committed.
          if (outcome.profile === undefined) {
            setProfile({
              revision: outcome.status.revision,
              content: result.content,
              embedding_version: profile?.embedding_version ?? '',
              has_matchable_resume:
                result.content.projects.length > 0 || result.content.experience.length > 0,
            });
          }
          setParagraphs([]);
          setSelectedFile(null);
          setPhase('PROFILE');
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
  }, [saving, draft, expectedRevision, controller, applyProfile, profile]);

  const deleteProfile = useCallback(async () => {
    if (profile === null || saving) return;
    setSaving(true);
    try {
      const response = await api.deleteProfile(profile.revision);
      setProfile(null);
      dispatchDraft({ type: 'CLEAR' });
      setParagraphs([]);
      setSelectedFile(null);
      setSaveStatus({
        kind: 'FAILED',
        code: 'DELETED',
        message: `Your resume details were deleted. Your account and browsing are unaffected. (revision ${response.resume_revision})`,
        retryable: false,
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
  }, [api, profile, saving, reload]);

  // keyTick forces the exposed key to be re-read after a save settles.
  void keyTick;

  return {
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
    unassignedParagraphs: paragraphs,
    saveStatus,
    saving,
    pendingIdempotencyKey: controller.pendingKey,
    actions: {
      reload,
      selectFiles,
      clearSelection,
      prepare,
      startManualEntry,
      editSavedProfile,
      cancelReview,
      assignParagraph,
      dismissParagraph,
      confirmSave,
      deleteProfile,
    },
  };
}

/** Exposed for tests that need to build the same draft the hook would. */
export function draftForContent(content: ResumeContent): ResumeDraft {
  return draftFromContent(content);
}
