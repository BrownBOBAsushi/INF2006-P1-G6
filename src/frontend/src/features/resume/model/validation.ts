import { LIMITS, type ResumeContent } from '../api/contractTypes';
import type { ResumeDraft } from './draft';
import {
  canonicalTextLength,
  isEmptyContent,
  requestBodyByteLength,
  toResumeContent,
} from './serialize';

/**
 * Client-side mirror of the resume_profiles bounds in DATA_API_CONTRACT.md.
 *
 * This is UX only. The server validates independently and remains authoritative;
 * nothing here weakens a server check. Its purpose is to give the student a specific
 * field-level message instead of a generic 422 after a round trip.
 */

export type IssueSeverity = 'error' | 'notice';

export interface ValidationIssue {
  severity: IssueSeverity;
  /** Stable machine-readable path, e.g. 'projects.2.description'. */
  path: string;
  code: string;
  message: string;
}

export interface ValidationResult {
  issues: ValidationIssue[];
  /** True when nothing blocks a save attempt. Notices do not block. */
  canSave: boolean;
  /** Normalised content that would be sent. */
  content: ResumeContent;
}

function error(path: string, code: string, message: string): ValidationIssue {
  return { severity: 'error', path, code, message };
}

function notice(path: string, code: string, message: string): ValidationIssue {
  return { severity: 'notice', path, code, message };
}

export function validateDraft(draft: ResumeDraft, expectedRevision: number): ValidationResult {
  const content = toResumeContent(draft);
  const issues: ValidationIssue[] = [];

  // --- blank-entry notices: removal must be visible, never silent -----------------
  const blankProjects = draft.projects.length - content.projects.length;
  if (blankProjects > 0) {
    issues.push(
      notice(
        'projects',
        'BLANK_ENTRIES_REMOVED',
        `${blankProjects} empty project ${blankProjects === 1 ? 'entry' : 'entries'} will not be saved.`,
      ),
    );
  }
  const blankExperience = draft.experience.length - content.experience.length;
  if (blankExperience > 0) {
    issues.push(
      notice(
        'experience',
        'BLANK_ENTRIES_REMOVED',
        `${blankExperience} empty experience ${blankExperience === 1 ? 'entry' : 'entries'} will not be saved.`,
      ),
    );
  }
  const blankEducation = draft.education.length - content.education.length;
  if (blankEducation > 0) {
    issues.push(
      notice(
        'education',
        'BLANK_ENTRIES_REMOVED',
        `${blankEducation} empty education ${blankEducation === 1 ? 'entry' : 'entries'} will not be saved.`,
      ),
    );
  }

  const rawSkillCount = draft.skills.filter((s) => s.value.trim().length > 0).length;
  if (rawSkillCount > content.skills.length) {
    const removed = rawSkillCount - content.skills.length;
    issues.push(
      notice(
        'skills',
        'DUPLICATE_SKILLS_REMOVED',
        `${removed} duplicate ${removed === 1 ? 'skill was' : 'skills were'} removed.`,
      ),
    );
  }

  // --- hard bounds ----------------------------------------------------------------
  if (isEmptyContent(content)) {
    issues.push(
      error(
        'content',
        'INVALID_CONTENT',
        'Add at least one skill, project, experience or education entry before saving.',
      ),
    );
  }

  if (content.skills.length > LIMITS.MAX_SKILLS) {
    issues.push(
      error(
        'skills',
        'INVALID_CONTENT',
        `Keep at most ${LIMITS.MAX_SKILLS} unique skills; you have ${content.skills.length}.`,
      ),
    );
  }
  content.skills.forEach((skill, index) => {
    if (skill.length > LIMITS.MAX_SKILL_CHARS) {
      issues.push(
        error(
          `skills.${index}`,
          'INVALID_CONTENT',
          `Skill "${skill.slice(0, 20)}…" exceeds ${LIMITS.MAX_SKILL_CHARS} characters.`,
        ),
      );
    }
  });

  const checkEntries = (
    entries: { title: string; description: string; technologies: string[] }[],
    section: 'projects' | 'experience',
    maxEntries: number,
    label: string,
  ) => {
    if (entries.length > maxEntries) {
      issues.push(
        error(
          section,
          'INVALID_CONTENT',
          `Keep at most ${maxEntries} ${label} entries; you have ${entries.length}.`,
        ),
      );
    }
    entries.forEach((entry, index) => {
      if (entry.title.length > LIMITS.MAX_TITLE_CHARS) {
        issues.push(
          error(
            `${section}.${index}.title`,
            'INVALID_CONTENT',
            `Title exceeds ${LIMITS.MAX_TITLE_CHARS} characters.`,
          ),
        );
      }
      if (entry.description.length > LIMITS.MAX_DESCRIPTION_CHARS) {
        issues.push(
          error(
            `${section}.${index}.description`,
            'INVALID_CONTENT',
            `Description exceeds ${LIMITS.MAX_DESCRIPTION_CHARS} characters (currently ${entry.description.length}).`,
          ),
        );
      }
      if (entry.technologies.length > LIMITS.MAX_TECHNOLOGIES) {
        issues.push(
          error(
            `${section}.${index}.technologies`,
            'INVALID_CONTENT',
            `Keep at most ${LIMITS.MAX_TECHNOLOGIES} technologies per entry.`,
          ),
        );
      }
      entry.technologies.forEach((tech, techIndex) => {
        if (tech.length > LIMITS.MAX_TECHNOLOGY_CHARS) {
          issues.push(
            error(
              `${section}.${index}.technologies.${techIndex}`,
              'INVALID_CONTENT',
              `Technology exceeds ${LIMITS.MAX_TECHNOLOGY_CHARS} characters.`,
            ),
          );
        }
      });
    });
  };

  checkEntries(content.projects, 'projects', LIMITS.MAX_PROJECTS, 'project');
  checkEntries(content.experience, 'experience', LIMITS.MAX_EXPERIENCE, 'experience');

  if (content.education.length > LIMITS.MAX_EDUCATION) {
    issues.push(
      error(
        'education',
        'INVALID_CONTENT',
        `Keep at most ${LIMITS.MAX_EDUCATION} education entries; you have ${content.education.length}.`,
      ),
    );
  }
  content.education.forEach((entry, index) => {
    if (entry.qualification.length > LIMITS.MAX_TITLE_CHARS) {
      issues.push(
        error(
          `education.${index}.qualification`,
          'INVALID_CONTENT',
          `Qualification exceeds ${LIMITS.MAX_TITLE_CHARS} characters.`,
        ),
      );
    }
    if (entry.details.length > LIMITS.MAX_DESCRIPTION_CHARS) {
      issues.push(
        error(
          `education.${index}.details`,
          'INVALID_CONTENT',
          `Details exceed ${LIMITS.MAX_DESCRIPTION_CHARS} characters.`,
        ),
      );
    }
  });

  const canonicalLength = canonicalTextLength(content);
  if (canonicalLength > LIMITS.MAX_CANONICAL_TEXT_CHARS) {
    issues.push(
      error(
        'content',
        'INVALID_CONTENT',
        `Total resume text is ${canonicalLength} characters; shorten it to ${LIMITS.MAX_CANONICAL_TEXT_CHARS} or fewer.`,
      ),
    );
  }

  const bodyBytes = requestBodyByteLength(expectedRevision, content);
  if (bodyBytes > LIMITS.MAX_JSON_BODY_BYTES) {
    issues.push(
      error('content', 'BODY_TOO_LARGE', 'The reviewed resume is too large to send. Shorten it.'),
    );
  }

  return {
    issues,
    canSave: !issues.some((i) => i.severity === 'error'),
    content,
  };
}

/**
 * Whether the saved profile can produce recommendations.
 * PRD: "Skills-only profiles may be saved but do not produce semantic recommendations
 * until a project/experience entry exists." The server reports has_matchable_resume;
 * this predicate only drives a pre-save hint.
 */
export function willBeMatchable(content: ResumeContent): boolean {
  return content.projects.length > 0 || content.experience.length > 0;
}
