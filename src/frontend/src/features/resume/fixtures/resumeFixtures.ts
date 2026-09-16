import type {
  ApiErrorEnvelope,
  PrepareResumeResponse,
  ResumeContent,
  ResumeProfileResponse,
} from '../api/contractTypes';

/**
 * Contract-shaped synthetic fixtures.
 *
 * SYNTHETIC ONLY. These are invented details for a fictional student, written to
 * exercise the contract shape. No real resume content may ever be committed here
 * (PRD P05, data/README.md).
 *
 * This module is imported by tests and by the development-only mock API. It must not
 * be imported by the feature root, so it is excluded from production bundles.
 */

export const SYNTHETIC_EMBEDDING_VERSION = 'all-MiniLM-L6-v2@synthetic-fixture';

export const syntheticPreparedContent: ResumeContent = {
  skills: ['Python', 'PostgreSQL', 'React', 'Docker'],
  projects: [
    {
      title: 'Course project: campus event finder',
      description:
        'Built a REST API in Python with a PostgreSQL database and wrote integration tests for the booking endpoints.',
      technologies: ['Python', 'PostgreSQL'],
    },
  ],
  experience: [
    {
      title: 'Software engineering intern',
      description:
        'Implemented API test coverage for an internal service and helped migrate a build pipeline to containers.',
      technologies: ['Python', 'Docker'],
    },
  ],
  education: [
    {
      qualification: 'BSc Computer Science',
      details: 'Currently studying; expected completion 2027.',
    },
  ],
};

/**
 * A prepare response including unclassified paragraphs.
 * The architecture doc requires unfamiliar headings to surface here rather than being
 * silently dropped, so the review screen can offer to assign them.
 */
export const syntheticPrepareResponse: PrepareResumeResponse = {
  draft: syntheticPreparedContent,
  unassigned_text:
    'Co-organised a student hackathon with about forty participants.\n\nVolunteer tutor for first-year programming labs.',
  warnings: [
    {
      code: 'SECTION_REVIEW_NEEDED',
      message: 'Some paragraphs could not be matched to a section. Review them before saving.',
    },
  ],
};

/** A prepare response where nothing could be classified — exercises the empty-draft path. */
export const syntheticUnclassifiedPrepareResponse: PrepareResumeResponse = {
  draft: { skills: [], projects: [], experience: [], education: [] },
  unassigned_text: 'Interested in backend development and distributed systems.',
  warnings: [
    {
      code: 'SECTION_REVIEW_NEEDED',
      message: 'No sections were recognised. Assign your details manually.',
    },
  ],
};

export const syntheticSavedProfile: ResumeProfileResponse = {
  revision: 4,
  content: syntheticPreparedContent,
  embedding_version: SYNTHETIC_EMBEDDING_VERSION,
  has_matchable_resume: true,
};

/** Saved profile with skills only: savable, but produces no recommendations (PRD P10). */
export const syntheticSkillsOnlyProfile: ResumeProfileResponse = {
  revision: 2,
  content: { skills: ['Python', 'Figma'], projects: [], experience: [], education: [] },
  embedding_version: SYNTHETIC_EMBEDDING_VERSION,
  has_matchable_resume: false,
};

/** Content as it would come back from a privacy re-check that stripped an email address. */
export const syntheticCleanedContent: ResumeContent = {
  ...syntheticPreparedContent,
  projects: [
    {
      title: 'Course project: campus event finder',
      description:
        'Built a REST API in Python with a PostgreSQL database and wrote integration tests for the booking endpoints. Contact details removed.',
      technologies: ['Python', 'PostgreSQL'],
    },
  ],
};

export function errorEnvelope(
  code: string,
  message: string,
  options: { retryable?: boolean; details?: Record<string, unknown> } = {},
): ApiErrorEnvelope {
  return {
    error: {
      code,
      message,
      request_id: 'test-request-id',
      retryable: options.retryable ?? false,
      details: options.details ?? {},
    },
  };
}

/**
 * Builds a File that behaves like a PDF for upload-validation tests.
 * `sizeBytes` is applied without allocating the bytes, so the 5 MiB boundary can be
 * tested without a 5 MiB allocation.
 */
export function syntheticPdfFile(
  name = 'synthetic-resume.pdf',
  sizeBytes = 1024,
  type = 'application/pdf',
): File {
  const file = new File(['%PDF-1.7 synthetic fixture'], name, { type });
  Object.defineProperty(file, 'size', { value: sizeBytes, configurable: true });
  return file;
}
