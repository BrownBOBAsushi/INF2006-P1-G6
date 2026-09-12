import type { ResumeContent } from '../api/contractTypes';
import type { ResumeDraft } from './draft';

/**
 * Converts the editable draft into exactly the ResumeContent shape the contract
 * accepts. The contract rejects extra fields, so this builds fresh objects with a
 * literal field whitelist rather than spreading the draft.
 *
 * Normalisation performed here mirrors what the contract says the server does, so the
 * student sees the same result they are about to send:
 *   - trim every string,
 *   - drop blank skills and blank technologies,
 *   - de-duplicate skills case-insensitively, keeping first occurrence and its casing
 *     (the contract caps "100 unique skills"),
 *   - drop entries that are entirely blank ("Blank entries removed with validation
 *     feedback"). The removal is reported by validation.ts, not silently hidden.
 *
 * `unassigned_text` is intentionally unreachable from here: it is not part of
 * ResumeDraft, so it cannot be serialised into a save body by accident.
 */

function uniqueTrimmed(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    const value = raw.trim();
    if (value.length === 0) continue;
    const key = value.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

function entryIsBlank(title: string, description: string, technologies: string[]): boolean {
  return title.length === 0 && description.length === 0 && technologies.length === 0;
}

export function toResumeContent(draft: ResumeDraft): ResumeContent {
  const skills = uniqueTrimmed(draft.skills.map((s) => s.value));

  const projects = draft.projects
    .map((p) => ({
      title: p.title.trim(),
      description: p.description.trim(),
      technologies: uniqueTrimmed(p.technologies.map((t) => t.value)),
    }))
    .filter((p) => !entryIsBlank(p.title, p.description, p.technologies));

  const experience = draft.experience
    .map((e) => ({
      title: e.title.trim(),
      description: e.description.trim(),
      technologies: uniqueTrimmed(e.technologies.map((t) => t.value)),
    }))
    .filter((e) => !entryIsBlank(e.title, e.description, e.technologies));

  const education = draft.education
    .map((e) => ({
      qualification: e.qualification.trim(),
      details: e.details.trim(),
    }))
    .filter((e) => e.qualification.length > 0 || e.details.length > 0);

  return { skills, projects, experience, education };
}

/** True when the content carries no information at all ("not all content may be blank"). */
export function isEmptyContent(content: ResumeContent): boolean {
  return (
    content.skills.length === 0 &&
    content.projects.length === 0 &&
    content.experience.length === 0 &&
    content.education.length === 0
  );
}

/**
 * Character count of the text the contract bounds at 50,000 ("whole canonical text").
 * The server owns the authoritative canonical serialisation and hash; this is a
 * client-side approximation used to warn before a pointless round trip.
 */
export function canonicalTextLength(content: ResumeContent): number {
  const parts: string[] = [...content.skills];
  for (const p of content.projects) parts.push(p.title, p.description, ...p.technologies);
  for (const e of content.experience) parts.push(e.title, e.description, ...e.technologies);
  for (const e of content.education) parts.push(e.qualification, e.details);
  return parts.reduce((total, part) => total + part.length, 0);
}

/** Byte size of the JSON body that will actually be sent (contract cap: 256 KiB). */
export function requestBodyByteLength(expectedRevision: number, content: ResumeContent): number {
  const body = JSON.stringify({ expected_revision: expectedRevision, content });
  return new TextEncoder().encode(body).length;
}

/**
 * Deterministic local signature of the content, with fixed key order.
 *
 * Used ONLY to decide whether a save attempt is the same logical attempt (same
 * idempotency key) or a new one. The authoritative "did anything change" answer is
 * the server's `changed` flag; this never overrides it.
 */
export function contentSignature(content: ResumeContent): string {
  return JSON.stringify([
    content.skills,
    content.projects.map((p) => [p.title, p.description, p.technologies]),
    content.experience.map((e) => [e.title, e.description, e.technologies]),
    content.education.map((e) => [e.qualification, e.details]),
  ]);
}

export function contentEquals(a: ResumeContent, b: ResumeContent): boolean {
  return contentSignature(a) === contentSignature(b);
}
