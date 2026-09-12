import type {
  ResumeContent,
  ResumeEducationEntry,
  ResumeExperienceEntry,
  ResumeProjectEntry,
} from '../api/contractTypes';

/**
 * Editable draft held ONLY in browser memory (PRD P07/P12: refresh or closing the
 * page loses unsaved drafts; nothing here is persisted to storage).
 *
 * Every list item carries a `localId` so React keeps input focus while editing.
 * `localId` is a rendering concern and is stripped in serialize.ts — the contract
 * rejects extra fields on ResumeContent.
 */

export interface DraftSkill {
  localId: string;
  value: string;
}

export interface DraftTechnology {
  localId: string;
  value: string;
}

export interface DraftProject {
  localId: string;
  title: string;
  description: string;
  technologies: DraftTechnology[];
}

export interface DraftExperience {
  localId: string;
  title: string;
  description: string;
  technologies: DraftTechnology[];
}

export interface DraftEducation {
  localId: string;
  qualification: string;
  details: string;
}

export interface ResumeDraft {
  skills: DraftSkill[];
  projects: DraftProject[];
  experience: DraftExperience[];
  education: DraftEducation[];
}

let localIdCounter = 0;

/**
 * Local ids only need to be unique within one page session. A counter is used rather
 * than crypto.randomUUID so draft construction stays deterministic in tests.
 */
export function nextLocalId(prefix = 'l'): string {
  localIdCounter += 1;
  return `${prefix}${localIdCounter}`;
}

/** Test-only reset so id assertions do not depend on test ordering. */
export function resetLocalIdCounterForTests(): void {
  localIdCounter = 0;
}

export function emptyDraft(): ResumeDraft {
  return { skills: [], projects: [], experience: [], education: [] };
}

export function newSkill(value = ''): DraftSkill {
  return { localId: nextLocalId('sk'), value };
}

export function newTechnology(value = ''): DraftTechnology {
  return { localId: nextLocalId('tech'), value };
}

export function newProject(partial: Partial<ResumeProjectEntry> = {}): DraftProject {
  return {
    localId: nextLocalId('pr'),
    title: partial.title ?? '',
    description: partial.description ?? '',
    technologies: (partial.technologies ?? []).map(newTechnology),
  };
}

export function newExperience(partial: Partial<ResumeExperienceEntry> = {}): DraftExperience {
  return {
    localId: nextLocalId('ex'),
    title: partial.title ?? '',
    description: partial.description ?? '',
    technologies: (partial.technologies ?? []).map(newTechnology),
  };
}

export function newEducation(partial: Partial<ResumeEducationEntry> = {}): DraftEducation {
  return {
    localId: nextLocalId('ed'),
    qualification: partial.qualification ?? '',
    details: partial.details ?? '',
  };
}

/** Build an editable draft from server-supplied content (prepare draft or saved profile). */
export function draftFromContent(content: ResumeContent): ResumeDraft {
  return {
    skills: (content.skills ?? []).map((s) => newSkill(s)),
    projects: (content.projects ?? []).map((p) => newProject(p)),
    experience: (content.experience ?? []).map((e) => newExperience(e)),
    education: (content.education ?? []).map((e) => newEducation(e)),
  };
}

/** True when the draft contains at least one project or experience entry with a description. */
export function draftHasMatchableEntry(draft: ResumeDraft): boolean {
  const hasBody = (e: { title: string; description: string }) =>
    e.title.trim().length > 0 || e.description.trim().length > 0;
  return draft.projects.some(hasBody) || draft.experience.some(hasBody);
}
