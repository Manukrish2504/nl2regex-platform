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
  pattern: string
  replacement: string
  columns: string[]
  error: { code: string; message: string } | null
  rows_total: number | null
  rows_changed: number | null
  attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type JobRequest = Pick<Job, 'file_key' | 'pattern' | 'replacement' | 'columns'>

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
