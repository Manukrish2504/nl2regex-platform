import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, CircleAlert, LoaderCircle, Plus } from 'lucide-react'

import { DataTable } from '@/components/data-table'
import { Link } from '@/components/link'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { useConnection } from '@/features/connection/api'
import { ApiError } from '@/lib/api'
import { fileName, resolveColumns } from '@/lib/utils'
import { cancelJob, isActive, useJob, useJobRows, type Job } from './api'
import { StatusBadge } from './status'

const PAGE_SIZES = [25, 50, 100]

export function JobPage({ jobId }: { jobId: string }) {
  const { data: connection, isPending: connectionPending } = useConnection()
  const job = useJob(jobId)

  if (connectionPending || (connection && job.isPending)) {
    return (
      <div className="flex w-full flex-col gap-4" aria-label="Loading the job">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-28 w-full" />
      </div>
    )
  }
  if (!connection || job.isError) {
    // A job belongs to the connection that created it, so both cases end in the same place.
    const notFound = job.error instanceof ApiError && job.error.status === 404
    return (
      <Unavailable
        title={!connection ? 'Connect to see this job' : notFound ? 'This job is not available' : 'Could not load the job'}
        message={
          !connection || notFound
            ? 'A job can only be opened from the connection that started it, and connections expire. Start a new transformation to run it again.'
            : (job.error?.message ?? 'Something went wrong.')
        }
      />
    )
  }
  return <JobView job={job.data!} />
}

function JobView({ job }: { job: Job }) {
  const queryClient = useQueryClient()
  const [cancelling, setCancelling] = useState(false)

  async function handleCancel() {
    setCancelling(true)
    const updated = await cancelJob(job.id).catch(() => null)
    if (updated) queryClient.setQueryData(['jobs', job.id], updated)
    queryClient.invalidateQueries({ queryKey: ['jobs'], exact: true })
    setCancelling(false)
  }

  const stopping = cancelling || job.cancel_requested
  // Until the pattern is written, an empty replacement or column list is not final: the sentence
  // may state them ("... in the Email column ... with 'REDACTED'"), and they arrive with the pattern.
  const awaitingSentence = Boolean(job.prompt) && !job.pattern && isActive(job)

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="min-w-0 truncate text-2xl font-medium tracking-tight" title={job.file_key}>
            {fileName(job.file_key)}
          </h1>
          <StatusBadge status={job.status} />
          <Button asChild variant="outline" size="sm" className="ml-auto rounded-full">
            <Link href="/">
              <Plus />
              New transformation
            </Link>
          </Button>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {job.prompt && (
            <>
              <dt className="text-muted-foreground">Asked</dt>
              <dd className="min-w-0 break-words">“{job.prompt}”</dd>
            </>
          )}
          <dt className="text-muted-foreground">Find</dt>
          <dd className="flex min-w-0 flex-col gap-1">
            {job.pattern ? (
              <span className="flex flex-wrap items-center gap-2">
                <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.8rem] break-all">{job.pattern}</code>
                {job.pattern_source !== 'user' && (
                  <Badge
                    variant="outline"
                    title={
                      job.pattern_source === 'cache'
                        ? 'The same request was answered before, so no language model was called this time.'
                        : 'Written by Claude from your sentence, then checked before it ran.'
                    }
                  >
                    {job.pattern_source === 'cache' ? 'from cache' : 'written by Claude'}
                  </Badge>
                )}
              </span>
            ) : isActive(job) ? (
              <Skeleton className="h-5 w-64" aria-label="The pattern is being written" />
            ) : (
              <span className="text-muted-foreground">no pattern was written</span>
            )}
            {job.explanation && <span className="text-xs text-muted-foreground">{job.explanation}</span>}
          </dd>
          <dt className="text-muted-foreground">Replace with</dt>
          <dd className="min-w-0">
            {job.replacement ? (
              <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.8rem] break-all">{job.replacement}</code>
            ) : (
              <span className="text-muted-foreground">
                {awaitingSentence ? 'being read from your sentence' : 'nothing (matches are removed)'}
              </span>
            )}
          </dd>
          <dt className="text-muted-foreground">In</dt>
          <dd className="flex flex-wrap gap-1.5">
            {job.columns.length ? (
              job.columns.map((column) => (
                <Badge key={column} variant="secondary">
                  {column}
                </Badge>
              ))
            ) : awaitingSentence ? (
              <span className="text-muted-foreground">being read from your sentence</span>
            ) : (
              <span>every column</span>
            )}
          </dd>
        </dl>
      </header>

      {isActive(job) && (
        <section className="flex flex-col gap-3 rounded-2xl border border-border bg-card/60 p-5" aria-live="polite">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="flex items-center gap-2">
              <LoaderCircle className="size-4 animate-spin text-primary" />
              {stopping ? 'Stopping…' : job.stage}
              {job.attempts > 1 && <span className="text-muted-foreground">(attempt {job.attempts})</span>}
            </span>
            <span className="text-muted-foreground tabular-nums">{job.progress}%</span>
          </div>
          <Progress value={job.progress} className="h-1.5" aria-label="Job progress" />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              This runs on a background worker. You can leave this page and come back from the sidebar.
            </p>
            <Button variant="outline" size="sm" onClick={handleCancel} disabled={stopping}>
              Cancel
            </Button>
          </div>
        </section>
      )}

      {job.status === 'FAILED' && (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertTitle>The job failed</AlertTitle>
          <AlertDescription>{job.error?.message ?? 'No reason was recorded.'}</AlertDescription>
        </Alert>
      )}

      {job.status === 'CANCELLED' && (
        <Alert>
          <CircleAlert />
          <AlertTitle>Cancelled at {job.progress}%</AlertTitle>
          <AlertDescription>Nothing was kept. The partial output has been deleted.</AlertDescription>
        </Alert>
      )}

      {job.status === 'SUCCESS' && <Results job={job} />}
    </div>
  )
}

function Results({ job }: { job: Job }) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0])
  const rows = useJobRows(job.id, page, pageSize, true)

  const total = job.rows_total ?? 0
  const lastPage = Math.max(1, Math.ceil(total / pageSize))
  const first = (page - 1) * pageSize + 1

  return (
    <section className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{total.toLocaleString()}</span> rows processed,{' '}
        <span className="font-medium text-foreground">{(job.rows_changed ?? 0).toLocaleString()}</span> changed.
      </p>

      {rows.isError ? (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertDescription>{rows.error.message}</AlertDescription>
        </Alert>
      ) : rows.data ? (
        <DataTable
          columns={rows.data.columns}
          rows={rows.data.rows}
          highlighted={job.columns.length ? resolveColumns(job.columns, rows.data.columns) : rows.data.columns}
          firstRowNumber={(rows.data.page - 1) * rows.data.page_size + 1}
          className={rows.isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}
        />
      ) : (
        <Skeleton className="h-64 w-full" />
      )}

      {total > 0 && (
        <nav aria-label="Result pages" className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground tabular-nums">
            Rows {first.toLocaleString()} to {Math.min(page * pageSize, total).toLocaleString()} of{' '}
            {total.toLocaleString()}
          </span>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-muted-foreground">
              Rows per page
              <select
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value))
                  setPage(1)
                }}
                className="h-8 rounded-lg border border-input bg-transparent px-2 text-foreground"
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="outline" size="icon" onClick={() => setPage(page - 1)} disabled={page <= 1} aria-label="Previous page">
              <ChevronLeft />
            </Button>
            <span className="tabular-nums">
              Page {page.toLocaleString()} of {lastPage.toLocaleString()}
            </span>
            <Button variant="outline" size="icon" onClick={() => setPage(page + 1)} disabled={page >= lastPage} aria-label="Next page">
              <ChevronRight />
            </Button>
          </div>
        </nav>
      )}
    </section>
  )
}

function Unavailable({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex w-full flex-col items-center gap-4 pt-[10vh] text-center">
      <h1 className="text-2xl font-medium tracking-tight">{title}</h1>
      <p className="max-w-md text-balance text-muted-foreground">{message}</p>
      <Button asChild>
        <Link href="/">
          <Plus />
          New transformation
        </Link>
      </Button>
    </div>
  )
}
