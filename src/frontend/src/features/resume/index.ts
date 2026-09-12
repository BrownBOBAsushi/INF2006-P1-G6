/**
 * Public surface of the resume feature (Nasya).
 *
 * Xue E's router should import only from here. Everything else is internal and may
 * change without coordination. Fixtures are deliberately NOT exported: importing them
 * from the feature root would pull synthetic data into the production bundle.
 */

export { ResumeWorkspace } from './components/ResumeWorkspace';
export type { ResumeWorkspaceProps } from './components/ResumeWorkspace';

export { createResumeApi } from './api/resumeApi';
export type { ResumeApiPort } from './api/resumeApi';
export type { HttpTransport, HttpRequest, HttpResponse, HttpMethod } from './api/httpTransport';

export { ApiError, UnknownOutcomeError } from './api/errors';
export type {
  ResumeContent,
  ResumeProfileResponse,
  PrepareResumeResponse,
} from './api/contractTypes';
