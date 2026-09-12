import { beforeEach, describe, expect, it } from 'vitest';
import { LIMITS } from '../api/contractTypes';
import { draftFromContent, emptyDraft, newSkill, resetLocalIdCounterForTests } from '../model/draft';
import { validateDraft, willBeMatchable } from '../model/validation';
import { syntheticPreparedContent } from '../fixtures/resumeFixtures';

beforeEach(() => resetLocalIdCounterForTests());

function errorCodes(draft: Parameters<typeof validateDraft>[0], revision = 0) {
  return validateDraft(draft, revision)
    .issues.filter((i) => i.severity === 'error')
    .map((i) => `${i.path}:${i.code}`);
}

describe('validateDraft', () => {
  it('accepts the synthetic prepared content', () => {
    const result = validateDraft(draftFromContent(syntheticPreparedContent), 0);
    expect(result.canSave).toBe(true);
    expect(result.issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('rejects completely blank content', () => {
    const result = validateDraft(emptyDraft(), 0);
    expect(result.canSave).toBe(false);
    expect(errorCodes(emptyDraft())).toContain('content:INVALID_CONTENT');
  });

  it('allows a skills-only profile but marks it unmatchable', () => {
    const draft = draftFromContent({
      skills: ['Python'],
      projects: [],
      experience: [],
      education: [],
    });
    const result = validateDraft(draft, 0);
    expect(result.canSave).toBe(true);
    expect(willBeMatchable(result.content)).toBe(false);
  });

  it('treats a single project as matchable', () => {
    const result = validateDraft(draftFromContent(syntheticPreparedContent), 0);
    expect(willBeMatchable(result.content)).toBe(true);
  });

  it('rejects more than 100 unique skills', () => {
    const skills = Array.from({ length: LIMITS.MAX_SKILLS + 1 }, (_, i) => `skill-${i}`);
    const draft = draftFromContent({ skills, projects: [], experience: [], education: [] });
    expect(errorCodes(draft)).toContain('skills:INVALID_CONTENT');
  });

  it('accepts exactly 100 unique skills', () => {
    const skills = Array.from({ length: LIMITS.MAX_SKILLS }, (_, i) => `skill-${i}`);
    const draft = draftFromContent({ skills, projects: [], experience: [], education: [] });
    expect(validateDraft(draft, 0).canSave).toBe(true);
  });

  it('rejects a skill longer than 100 characters', () => {
    const draft = draftFromContent({
      skills: ['x'.repeat(LIMITS.MAX_SKILL_CHARS + 1)],
      projects: [],
      experience: [],
      education: [],
    });
    expect(errorCodes(draft)).toContain('skills.0:INVALID_CONTENT');
  });

  it('rejects more than 20 project entries', () => {
    const projects = Array.from({ length: LIMITS.MAX_PROJECTS + 1 }, (_, i) => ({
      title: `Project ${i}`,
      description: 'Did something.',
      technologies: [],
    }));
    const draft = draftFromContent({ skills: [], projects, experience: [], education: [] });
    expect(errorCodes(draft)).toContain('projects:INVALID_CONTENT');
  });

  it('rejects more than 10 education entries', () => {
    const education = Array.from({ length: LIMITS.MAX_EDUCATION + 1 }, (_, i) => ({
      qualification: `Qualification ${i}`,
      details: '',
    }));
    const draft = draftFromContent({ skills: [], projects: [], experience: [], education });
    expect(errorCodes(draft)).toContain('education:INVALID_CONTENT');
  });

  it('rejects a description longer than 5000 characters and names the field', () => {
    const draft = draftFromContent({
      skills: [],
      projects: [
        {
          title: 'Long one',
          description: 'y'.repeat(LIMITS.MAX_DESCRIPTION_CHARS + 1),
          technologies: [],
        },
      ],
      experience: [],
      education: [],
    });
    expect(errorCodes(draft)).toContain('projects.0.description:INVALID_CONTENT');
  });

  it('rejects more than 30 technologies on one entry', () => {
    const technologies = Array.from({ length: LIMITS.MAX_TECHNOLOGIES + 1 }, (_, i) => `tech-${i}`);
    const draft = draftFromContent({
      skills: [],
      projects: [{ title: 'T', description: 'D', technologies }],
      experience: [],
      education: [],
    });
    expect(errorCodes(draft)).toContain('projects.0.technologies:INVALID_CONTENT');
  });

  it('rejects total canonical text beyond 50,000 characters', () => {
    // Twelve entries of 4,500 characters each stays under every per-field bound
    // but exceeds the whole-resume cap.
    const projects = Array.from({ length: 12 }, (_, i) => ({
      title: `Entry ${i}`,
      description: 'z'.repeat(4_500),
      technologies: [],
    }));
    const draft = draftFromContent({ skills: [], projects, experience: [], education: [] });
    const codes = errorCodes(draft);
    expect(codes).toContain('content:INVALID_CONTENT');
  });

  it('reports removed blank entries as a notice rather than silently dropping them', () => {
    const draft = draftFromContent(syntheticPreparedContent);
    draft.projects.push({ localId: 'blank-1', title: '  ', description: '', technologies: [] });
    const result = validateDraft(draft, 0);
    const notices = result.issues.filter((i) => i.severity === 'notice');
    expect(notices.map((n) => n.code)).toContain('BLANK_ENTRIES_REMOVED');
    // A notice must not block saving.
    expect(result.canSave).toBe(true);
    expect(result.content.projects).toHaveLength(1);
  });

  it('reports removed duplicate skills as a notice', () => {
    const draft = draftFromContent(syntheticPreparedContent);
    draft.skills.push(newSkill('python'));
    const result = validateDraft(draft, 0);
    expect(result.issues.map((i) => i.code)).toContain('DUPLICATE_SKILLS_REMOVED');
    expect(result.canSave).toBe(true);
  });

  it('returns the normalised content that would actually be sent', () => {
    const draft = draftFromContent({
      skills: ['  React  '],
      projects: [],
      experience: [],
      education: [],
    });
    expect(validateDraft(draft, 0).content.skills).toEqual(['React']);
  });
});
