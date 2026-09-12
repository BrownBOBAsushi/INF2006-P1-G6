import type { ResumeContent } from '../api/contractTypes';
import {
  draftFromContent,
  emptyDraft,
  newEducation,
  newExperience,
  newProject,
  newSkill,
  newTechnology,
  type ResumeDraft,
} from './draft';

/** Sections that share the title/description/technologies shape. */
export type EntrySection = 'projects' | 'experience';

export type DraftAction =
  | { type: 'SET_CONTENT'; content: ResumeContent }
  | { type: 'CLEAR' }
  | { type: 'ADD_SKILL'; value?: string }
  | { type: 'UPDATE_SKILL'; localId: string; value: string }
  | { type: 'REMOVE_SKILL'; localId: string }
  | { type: 'ADD_ENTRY'; section: EntrySection; description?: string; title?: string }
  | {
      type: 'UPDATE_ENTRY';
      section: EntrySection;
      localId: string;
      field: 'title' | 'description';
      value: string;
    }
  | { type: 'REMOVE_ENTRY'; section: EntrySection; localId: string }
  | { type: 'ADD_TECHNOLOGY'; section: EntrySection; localId: string }
  | {
      type: 'UPDATE_TECHNOLOGY';
      section: EntrySection;
      localId: string;
      techLocalId: string;
      value: string;
    }
  | { type: 'REMOVE_TECHNOLOGY'; section: EntrySection; localId: string; techLocalId: string }
  | { type: 'ADD_EDUCATION' }
  | {
      type: 'UPDATE_EDUCATION';
      localId: string;
      field: 'qualification' | 'details';
      value: string;
    }
  | { type: 'REMOVE_EDUCATION'; localId: string };

export function draftReducer(state: ResumeDraft, action: DraftAction): ResumeDraft {
  switch (action.type) {
    case 'SET_CONTENT':
      return draftFromContent(action.content);

    case 'CLEAR':
      return emptyDraft();

    case 'ADD_SKILL':
      return { ...state, skills: [...state.skills, newSkill(action.value ?? '')] };

    case 'UPDATE_SKILL':
      return {
        ...state,
        skills: state.skills.map((s) =>
          s.localId === action.localId ? { ...s, value: action.value } : s,
        ),
      };

    case 'REMOVE_SKILL':
      return { ...state, skills: state.skills.filter((s) => s.localId !== action.localId) };

    case 'ADD_ENTRY': {
      const factory = action.section === 'projects' ? newProject : newExperience;
      const entry = factory({
        title: action.title ?? '',
        description: action.description ?? '',
        technologies: [],
      });
      return { ...state, [action.section]: [...state[action.section], entry] } as ResumeDraft;
    }

    case 'UPDATE_ENTRY':
      return {
        ...state,
        [action.section]: state[action.section].map((entry) =>
          entry.localId === action.localId ? { ...entry, [action.field]: action.value } : entry,
        ),
      } as ResumeDraft;

    case 'REMOVE_ENTRY':
      return {
        ...state,
        [action.section]: state[action.section].filter((e) => e.localId !== action.localId),
      } as ResumeDraft;

    case 'ADD_TECHNOLOGY':
      return {
        ...state,
        [action.section]: state[action.section].map((entry) =>
          entry.localId === action.localId
            ? { ...entry, technologies: [...entry.technologies, newTechnology('')] }
            : entry,
        ),
      } as ResumeDraft;

    case 'UPDATE_TECHNOLOGY':
      return {
        ...state,
        [action.section]: state[action.section].map((entry) =>
          entry.localId === action.localId
            ? {
                ...entry,
                technologies: entry.technologies.map((t) =>
                  t.localId === action.techLocalId ? { ...t, value: action.value } : t,
                ),
              }
            : entry,
        ),
      } as ResumeDraft;

    case 'REMOVE_TECHNOLOGY':
      return {
        ...state,
        [action.section]: state[action.section].map((entry) =>
          entry.localId === action.localId
            ? {
                ...entry,
                technologies: entry.technologies.filter((t) => t.localId !== action.techLocalId),
              }
            : entry,
        ),
      } as ResumeDraft;

    case 'ADD_EDUCATION':
      return { ...state, education: [...state.education, newEducation()] };

    case 'UPDATE_EDUCATION':
      return {
        ...state,
        education: state.education.map((e) =>
          e.localId === action.localId ? { ...e, [action.field]: action.value } : e,
        ),
      };

    case 'REMOVE_EDUCATION':
      return { ...state, education: state.education.filter((e) => e.localId !== action.localId) };

    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

/**
 * Splits the transient `unassigned_text` field into paragraphs the student can assign.
 * This text is never saved and never embedded; the review screen only offers to copy
 * it into a project or experience entry, or to leave it out.
 */
export function unassignedParagraphs(unassignedText: string): string[] {
  return unassignedText
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}
