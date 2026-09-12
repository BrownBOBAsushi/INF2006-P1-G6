import { beforeEach, describe, expect, it } from 'vitest';
import {
  draftFromContent,
  newExperience,
  newProject,
  newSkill,
  resetLocalIdCounterForTests,
} from '../model/draft';
import {
  canonicalTextLength,
  contentEquals,
  contentSignature,
  isEmptyContent,
  toResumeContent,
} from '../model/serialize';
import { syntheticPreparedContent } from '../fixtures/resumeFixtures';

beforeEach(() => resetLocalIdCounterForTests());

describe('toResumeContent', () => {
  it('produces exactly the four contract fields and nothing else', () => {
    const content = toResumeContent(draftFromContent(syntheticPreparedContent));
    expect(Object.keys(content).sort()).toEqual([
      'education',
      'experience',
      'projects',
      'skills',
    ]);
  });

  it('strips local render ids from every nested entry', () => {
    const draft = draftFromContent(syntheticPreparedContent);
    // localIds exist on the draft...
    expect(draft.projects[0]?.localId).toBeTruthy();
    expect(draft.projects[0]?.technologies[0]?.localId).toBeTruthy();

    // ...but must not survive serialization: the contract rejects extra fields.
    const content = toResumeContent(draft);
    const serialized = JSON.stringify(content);
    expect(serialized).not.toContain('localId');
    expect(Object.keys(content.projects[0] as object).sort()).toEqual([
      'description',
      'technologies',
      'title',
    ]);
    expect(Object.keys(content.education[0] as object).sort()).toEqual([
      'details',
      'qualification',
    ]);
  });

  it('trims whitespace and drops blank skills', () => {
    const draft = draftFromContent({
      skills: ['  Python  ', '   ', 'React'],
      projects: [],
      experience: [],
      education: [],
    });
    expect(toResumeContent(draft).skills).toEqual(['Python', 'React']);
  });

  it('de-duplicates skills case-insensitively, keeping the first casing', () => {
    const draft = draftFromContent({
      skills: ['PostgreSQL', 'postgresql', 'POSTGRESQL', 'Docker'],
      projects: [],
      experience: [],
      education: [],
    });
    expect(toResumeContent(draft).skills).toEqual(['PostgreSQL', 'Docker']);
  });

  it('removes entirely blank project and experience entries', () => {
    const draft = draftFromContent(syntheticPreparedContent);
    draft.projects.push(newProject({ title: '  ', description: '', technologies: [] }));
    draft.experience.push(newExperience({ title: '', description: '   ' }));
    const content = toResumeContent(draft);
    expect(content.projects).toHaveLength(1);
    expect(content.experience).toHaveLength(1);
  });

  it('keeps an entry that has only a description', () => {
    const draft = draftFromContent({
      skills: [],
      projects: [{ title: '', description: 'Built a small parser.', technologies: [] }],
      experience: [],
      education: [],
    });
    expect(toResumeContent(draft).projects).toEqual([
      { title: '', description: 'Built a small parser.', technologies: [] },
    ]);
  });

  it('keeps an education entry with only details', () => {
    const draft = draftFromContent({
      skills: [],
      projects: [],
      experience: [],
      education: [{ qualification: '', details: 'Currently studying' }],
    });
    expect(toResumeContent(draft).education).toHaveLength(1);
  });
});

describe('content helpers', () => {
  it('detects fully empty content', () => {
    expect(isEmptyContent({ skills: [], projects: [], experience: [], education: [] })).toBe(true);
    expect(isEmptyContent(syntheticPreparedContent)).toBe(false);
  });

  it('counts canonical text across every field', () => {
    const length = canonicalTextLength({
      skills: ['abcd'],
      projects: [{ title: 'ab', description: 'cde', technologies: ['fg'] }],
      experience: [],
      education: [{ qualification: 'h', details: 'ij' }],
    });
    expect(length).toBe(4 + 2 + 3 + 2 + 1 + 2);
  });

  it('gives a stable signature that ignores draft identity but not content', () => {
    const a = toResumeContent(draftFromContent(syntheticPreparedContent));
    const b = toResumeContent(draftFromContent(syntheticPreparedContent));
    expect(contentSignature(a)).toBe(contentSignature(b));
    expect(contentEquals(a, b)).toBe(true);

    const draftC = draftFromContent(syntheticPreparedContent);
    draftC.skills.push(newSkill('Rust'));
    expect(contentEquals(toResumeContent(draftC), a)).toBe(false);
  });

  it('treats reordered skills as different content', () => {
    const first = toResumeContent(
      draftFromContent({ skills: ['A', 'B'], projects: [], experience: [], education: [] }),
    );
    const second = toResumeContent(
      draftFromContent({ skills: ['B', 'A'], projects: [], experience: [], education: [] }),
    );
    expect(contentEquals(first, second)).toBe(false);
  });
});
