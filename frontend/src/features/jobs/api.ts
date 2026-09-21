import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { useConnection } from '@/features/connection/api'
import { api } from '@/lib/api'

export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED'

export type Job = {
  id: string
  status: JobStatus
  progress: number
  stage: string
  cancel_requested: boolean
  file_key: string
  file_format: 'csv' | 'excel'
  kind: JobKind
  /** Set when this job ran on an earlier job's result rather than on the file in the bucket. */
  source_job_id: string | null
  /** The plain-English request, when the pattern was not typed. */
  prompt: string | null
  /** Empty while a worker is still writing it from the prompt. */
  pattern: string
  pattern_source: 'user' | 'llm' | 'cache'
  explanation: string | null
  replacement: string
  columns: string[]
  /** What a language model decided and what that changed, for the kinds it plans. */
  report: PiiReport | StandardiseReport | null
  error: { code: string; message: string } | null
  rows_total: number | null
  rows_changed: number | null
  attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type JobKind = 'replace' | 'redact_pii' | 'standardise'

export type PiiReport = {
  findings: { column: string; kind: string; reason: string }[]
  skipped: { column: string; kind: string; reason: string; skipped_because: string }[]
  operations: { kind: string; placeholder: string; columns: string[]; rows_changed?: number }[]
  from_cache: boolean
}

export type StandardiseReport = {
  column: string
  mapping: { from: string; to: string; rows: number }[]
  distinct_before: number
  distinct_after: number
  from_cache: boolean
}

type Target = { file_key: string } | { source_job_id: string }

export type JobRequest = Pick<Job, 'columns'> &
  Target &
  (
    | { kind?: 'replace'; replacement: string; pattern: string }
    | { kind?: 'replace'; replacement: string; prompt: string }
    | { kind: 'redact_pii' }
    | { kind: 'standardise'; prompt?: string }
  )

export const KIND_LABELS: Record<JobKind, string> = {
  replace: 'Find and replace',
  redact_pii: 'Redact personal data',
  standardise: 'Standardise a column',
}

export type Page = {
  columns: string[]
  rows: (string | null)[][]
  page: number
  page_size: number
  total_rows: number
}

export const isActive = (job: Job) => job.status === 'QUEUED' || job.status === 'RUNNING'

/** This connection's recent jobs. Polls only while one of them is still in progress. */
export function useJobs() {
  const { data: connection } = useConnection()
  return useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<{ jobs: Job[] }>('/jobs/').then((body) => body.jobs),
    enabled: Boolean(connection),
    refetchInterval: (query) => (query.state.data?.some(isActive) ? 3000 : false),
  })
}

/** One job, polled every second until it finishes. */
export function useJob(id: string) {
  const { data: connection } = useConnection()
  return useQuery({
    queryKey: ['jobs', id],
    queryFn: () => api<Job>(`/jobs/${id}/`),
    enabled: Boolean(connection),
    refetchInterval: (query) => (!query.state.data || isActive(query.state.data) ? 1000 : false),
  })
}

export function useJobRows(id: string, page: number, pageSize: number, enabled: boolean) {
  return useQuery({
    queryKey: ['jobs', id, 'rows', page, pageSize],
    queryFn: () => api<Page>(`/jobs/${id}/rows/?page=${page}&page_size=${pageSize}`),
    enabled,
    // Keep showing the current page while the next one loads, so the table never blanks out.
    placeholderData: keepPreviousData,
    staleTime: Infinity, // a finished job's rows never change
  })
}

export function submitJob(request: JobRequest) {
  return api<Job>('/jobs/', { method: 'POST', body: JSON.stringify(request) })
}

export function cancelJob(id: string) {
  return api<Job>(`/jobs/${id}/cancel/`, { method: 'POST' })
}

/**
 * A job and everything it was built on, oldest first: a conversation about one file.
 *
 * The links are followed inside the list the sidebar already has, so opening a job costs no
 * extra requests. A parent older than that list simply starts the chain later.
 */
export function chainOf(job: Job, jobs: Job[] = []): Job[] {
  const chain = [job]
  const byId = new Map(jobs.map((one) => [one.id, one]))
  for (let parent = job.source_job_id && byId.get(job.source_job_id); parent; ) {
    chain.unshift(parent)
    parent = parent.source_job_id ? byId.get(parent.source_job_id) : undefined
  }
  return chain
}

/** The last job of each conversation: what the sidebar lists, one line per conversation. */
export function latestOfEachChain(jobs: Job[]): Job[] {
  const followed = new Set(jobs.map((job) => job.source_job_id).filter(Boolean))
  return jobs.filter((job) => !followed.has(job.id))
}

