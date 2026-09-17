/** Provisional wire types from DATA_API_CONTRACT.md, pending Jiaxin's OpenAPI. */
export const filterOptions = {
  job_type: ['INTERNSHIP', 'OTHER', 'UNKNOWN'],
  employment_time: ['FULL_TIME', 'PART_TIME', 'UNKNOWN'],
  work_arrangement: ['ON_SITE', 'HYBRID', 'REMOTE', 'UNKNOWN'],
} as const;
export type FilterKey = keyof typeof filterOptions;
export interface JobSummary {
  job_id: string;
  title: string;
  company_name: string;
  country_code: string;
  location: string;
  job_type: typeof filterOptions.job_type[number];
  employment_time: typeof filterOptions.employment_time[number];
  work_arrangement: typeof filterOptions.work_arrangement[number];
  posted_at: string | null;
  last_imported_at: string;
  is_active: boolean;
}
export interface JobDetail extends JobSummary {
  description: string;
  apply_url: string;
  source: string;
  source_url: string;
  last_verified_at: string | null;
  eligibility_notes: { text: string; source_quote: string }[];
  requirements: {
    requirement_id: string;
    requirement_text: string;
    importance: 'REQUIRED' | 'PREFERRED';
    alternatives: string[];
    source_quote: string;
  }[];
}
export interface JobPage {
  items: JobSummary[];
  total: number;
  limit: number;
  offset: number;
  catalogue_revision: number;
}
export interface Me {
  user: { user_id: string; display_name: string | null };
  resume_revision: number;
  has_resume: boolean;
  has_matchable_resume: boolean;
  csrf_token: string;
}
