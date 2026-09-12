/**
 * Resume-related request/response shapes from docs/handoff/DATA_API_CONTRACT.md.
 *
 * These are hand-written against the written contract because the backend does not
 * exist yet and no OpenAPI document has been generated. Once Jiaxin generates
 * OpenAPI and Xue E wires the generated client, these types should be replaced by
 * the generated equivalents and this file reduced to feature-local view models.
 * Until then this file is the single place Nasya's feature encodes the contract.
 *
 * Field names use the contract's snake_case wire format deliberately: they are the
 * JSON that crosses the network, not internal naming.
 */

// --- ResumeContent: the fixed JSON shape stored in resume_profiles.content -------

export interface ResumeProjectEntry {
  title: string;
  description: string;
  technologies: string[];
}

export interface ResumeExperienceEntry {
  title: string;
  description: string;
  technologies: string[];
}

export interface ResumeEducationEntry {
  qualification: string;
  details: string;
}

export interface ResumeContent {
  skills: string[];
  projects: ResumeProjectEntry[];
  experience: ResumeExperienceEntry[];
  education: ResumeEducationEntry[];
}

/** Key order used when the client needs a deterministic local signature. */
export const RESUME_CONTENT_KEYS = ['skills', 'projects', 'experience', 'education'] as const;

// --- POST /api/resume/prepare ---------------------------------------------------

export interface PrepareWarning {
  code: string;
  message: string;
}

export interface PrepareResumeResponse {
  draft: ResumeContent;
  /**
   * Transient cleaned paragraphs the extractor could not classify.
   * Architecture doc: never part of saved ResumeContent, never embedded directly.
   */
  unassigned_text: string;
  warnings: PrepareWarning[];
}

// --- GET /api/resume ------------------------------------------------------------

export interface ResumeProfileResponse {
  revision: number;
  content: ResumeContent;
  embedding_version: string;
  has_matchable_resume: boolean;
}

// --- PUT /api/resume ------------------------------------------------------------

export interface SaveResumeRequest {
  expected_revision: number;
  content: ResumeContent;
}

export interface SaveResumeResponse {
  operation_id: string;
  result_revision: number;
  changed: boolean;
}

// --- DELETE /api/resume ---------------------------------------------------------

export interface DeleteResumeRequest {
  expected_revision: number;
}

export interface DeleteResumeResponse {
  resume_revision: number;
  has_resume: false;
}

// --- GET /api/resume/operations/{id} --------------------------------------------

export type OperationState = 'PROCESSING' | 'SUCCEEDED' | 'FAILED';

export interface OperationStatusResponse {
  operation_id: string;
  state: OperationState;
  result_revision: number | null;
  failure_code: string | null;
}

// --- Error envelope -------------------------------------------------------------

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id: string;
    retryable: boolean;
    details?: Record<string, unknown>;
  };
}

/** Error codes this feature reacts to specifically. Others fall through to generic handling. */
export const ERROR_CODES = {
  AUTH_REQUIRED: 'AUTH_REQUIRED',
  SESSION_EXPIRED: 'SESSION_EXPIRED',
  CSRF_INVALID: 'CSRF_INVALID',
  RESUME_NOT_FOUND: 'RESUME_NOT_FOUND',
  OPERATION_EXPIRED: 'OPERATION_EXPIRED',
  REVISION_CONFLICT: 'REVISION_CONFLICT',
  IDEMPOTENCY_CONFLICT: 'IDEMPOTENCY_CONFLICT',
  SAVE_IN_PROGRESS: 'SAVE_IN_PROGRESS',
  FILE_TOO_LARGE: 'FILE_TOO_LARGE',
  BODY_TOO_LARGE: 'BODY_TOO_LARGE',
  PDF_REQUIRED: 'PDF_REQUIRED',
  PDF_UNREADABLE: 'PDF_UNREADABLE',
  PDF_ENCRYPTED: 'PDF_ENCRYPTED',
  TEXT_REQUIRED: 'TEXT_REQUIRED',
  REVIEW_REQUIRED: 'REVIEW_REQUIRED',
  INVALID_CONTENT: 'INVALID_CONTENT',
  RESUME_REQUIRED: 'RESUME_REQUIRED',
  INSUFFICIENT_RESUME_INFORMATION: 'INSUFFICIENT_RESUME_INFORMATION',
  PROCESSING_BUSY: 'PROCESSING_BUSY',
  MODEL_VERSION_UNAVAILABLE: 'MODEL_VERSION_UNAVAILABLE',
  SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
  PROCESSING_TIMEOUT: 'PROCESSING_TIMEOUT',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

// --- Contract limits used by client-side validation -----------------------------

export const LIMITS = {
  MAX_SKILLS: 100,
  MAX_SKILL_CHARS: 100,
  MAX_PROJECTS: 20,
  MAX_EXPERIENCE: 20,
  MAX_EDUCATION: 10,
  MAX_TITLE_CHARS: 200,
  MAX_DESCRIPTION_CHARS: 5_000,
  MAX_TECHNOLOGIES: 30,
  MAX_TECHNOLOGY_CHARS: 100,
  MAX_CANONICAL_TEXT_CHARS: 50_000,
  MAX_JSON_BODY_BYTES: 256 * 1024,
  /** architecture.md: PDF part cap exactly 5,242,880 bytes, one file. */
  MAX_PDF_BYTES: 5_242_880,
} as const;

/** Capped backoff from IMPLEMENTATION_GUIDE.md: 3, 6, 12 seconds, then manual retry. */
export const RETRY_BACKOFF_SECONDS = [3, 6, 12] as const;
