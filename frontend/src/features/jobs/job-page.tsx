import { useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ChevronRight,
  CircleAlert,
  Copy,
  LoaderCircle,
  PanelRight,
  RotateCcw,
  Table2,
} from 'lucide-react'

import { Diamond } from '@/components/diamond'
import { Link } from '@/components/link'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useConnection } from '@/features/connection/api'
import { ApiError } from '@/lib/api'
import { cn, duration, fileName } from '@/lib/utils'
import {
  cancelJob,
  isActive,
  useJob,
  type Job,
  type PiiReport,
  type StandardiseReport,
} from './api'

interface JobPageProps {
  jobId: string
  panelOpen: boolean
  onPanelOpenChange: (open: boolean) => void
}

/**
 * One job, read as a conversation: what was asked, what the system decided, and what it did.
 * The rows themselves live in the panel beside it, because a million rows are not a message.
 */
export function JobPage({ jobId, panelOpen, onPanelOpenChange }: JobPageProps) {
  const { data: connection, isPending: connectionPending } = useConnection()
  const job = useJob(jobId)
  const finished = job.data?.status === 'SUCCESS'

  // The results open by themselves the moment there are any.
  useEffect(() => {
    if (finished) onPanelOpenChange(true)
  }, [finished, onPanelOpenChange])

  if (connectionPending || (connection && job.isPending)) {
    return (
      <div className="flex flex-col gap-4 px-6 pt-10" aria-label="Loading the job">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }
  if (!connection || job.isError) {
    const notFound = job.error instanceof ApiError && job.error.status === 404
    return (
      <Unavailable
        title={
          !connection
            ? 'Connect to see this job'
            : notFound
              ? 'This job is not available'
              : 'Could not load the job'
        }
        message={
          !connection || notFound
            ? 'A job can only be opened from the connection that started it, and connections expire. Start a new transformation to run it again.'
            : (job.error?.message ?? 'Something went wrong.')
        }
      />
    )
  }
  return <Conversation job={job.data!} panelOpen={panelOpen} onPanelOpenChange={onPanelOpenChange} />
}

function Conversation({ job, panelOpen, onPanelOpenChange }: { job: Job } & Omit<JobPageProps, 'jobId'>) {
  const queryClient = useQueryClient()
  const [cancelling, setCancelling] = useState(false)
  const stopping = cancelling || job.cancel_requested

  async function handleCancel() {
    setCancelling(true)
    const updated = await cancelJob(job.id).catch(() => null)
    if (updated) queryClient.setQueryData(['jobs', job.id], updated)
    queryClient.invalidateQueries({ queryKey: ['jobs'], exact: true })
    setCancelling(false)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[720px] flex-col gap-8 px-6 py-8">
          <Asked job={job} />
          <Answer job={job} panelOpen={panelOpen} onPanelOpenChange={onPanelOpenChange} />
        </div>
      </div>

      <div className="shrink-0 px-6 pb-5">
        <div className="mx-auto w-full max-w-[720px]">
          {isActive(job) ? (
            <div
              className="flex flex-col gap-2.5 rounded-[14px] bg-[#0b100f] p-3.5 shadow-[inset_0_0_0_1px_var(--surface-edge)]"
              aria-live="polite"
            >
              <div className="flex items-center gap-2.5 text-[13px]">
                <LoaderCircle className="size-3.5 shrink-0 animate-spin text-primary" />
                <span className="min-w-0 flex-1 truncate">
                  {stopping ? 'Stopping…' : job.stage}
                </span>
                {job.attempts > 1 && (
                  <span className="font-mono text-[11px] text-dim">attempt {job.attempts}</span>
                )}
                <span className="font-mono text-[11px] text-dim tabular-nums">{job.progress}%</span>
                <Button variant="ghost" size="sm" onClick={handleCancel} disabled={stopping}>
                  Cancel
                </Button>
              </div>
              <div className="h-[3px] overflow-hidden rounded-full bg-[#141b19]">
                <div
                  role="progressbar"
                  aria-label="Job progress"
                  aria-valuenow={job.progress}
                  className="h-full rounded-full bg-primary transition-[width] duration-500"
                  style={{ width: `${Math.max(job.progress, 2)}%` }}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild variant="outline" size="sm">
                <Link href="/">
                  <RotateCcw className="size-3.5" />
                  New transformation
                </Link>
              </Button>
              {job.status === 'SUCCESS' && !panelOpen && (
                <Button variant="ghost" size="sm" onClick={() => onPanelOpenChange(true)}>
                  <PanelRight className="size-3.5" />
                  Show the rows
                </Button>
              )}
            </div>
          )}
          <p className="pt-2.5 text-center text-[11px] text-dim">
            Your file is never modified. Every job writes a separate copy, and the bucket is opened
            read-only.
          </p>
        </div>
      </div>
    </div>
  )
}

/** The request, as the person made it. */
function Asked({ job }: { job: Job }) {
  const said =
    job.kind === 'replace'
      ? (job.prompt ?? job.pattern)
      : job.kind === 'standardise'
        ? `Standardise ${job.columns[0] ?? 'a column'}${job.prompt ? ` — ${job.prompt}` : ''}`
        : 'Find the personal data in this file and mask it'

  return (
    <div className="flex justify-end">
      <p
        className={cn(
          'max-w-[85%] rounded-[13px] bg-[#0d1211] px-4 py-3 text-[15.5px] leading-relaxed inset-ring inset-ring-[#17201e]',
          job.kind === 'replace' && !job.prompt && 'font-mono text-[13px]',
        )}
      >
        {said}
      </p>
    </div>
  )
}

/** What the system decided and did, in the voice of the application. */
function Answer({ job, panelOpen, onPanelOpenChange }: { job: Job } & Omit<JobPageProps, 'jobId'>) {
  const writing = job.kind === 'replace' && Boolean(job.prompt) && !job.pattern

  return (
    <div className="flex flex-col gap-4">
      <p className="eyebrow flex items-center gap-2 text-primary">
        <Diamond />
        nl2regex
      </p>

      {job.kind === 'replace' && (
        <div className="flex flex-col gap-2.5">
          {writing ? (
            <Skeleton
              className="h-9 w-72 rounded-[10px]"
              aria-label="The pattern is being written"
            />
          ) : (
            <CodeCard
              label={job.pattern_source === 'user' ? 'Your pattern' : 'Pattern'}
              code={job.pattern}
              badge={
                job.pattern_source === 'user'
                  ? undefined
                  : job.pattern_source === 'cache'
                    ? 'from cache'
                    : 'written by Claude'
              }
            />
          )}
          {job.explanation && (
            <p className="text-[15.5px] leading-relaxed text-[#cdd8d5]">{job.explanation}</p>
          )}
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
            <div className="flex gap-2">
              <dt className="text-dim">Replace with</dt>
              <dd className="font-mono text-[12px]">
                {job.replacement || (
                  <span className="font-sans text-dim">
                    {writing ? 'from your sentence' : 'nothing'}
                  </span>
                )}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-dim">In</dt>
              <dd>
                {job.columns.length
                  ? job.columns.join(', ')
                  : writing
                    ? 'from your sentence'
                    : 'every column'}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {job.report && <Report job={job} />}

      {job.status === 'FAILED' && (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertTitle>The job failed</AlertTitle>
          <AlertDescription>{job.error?.message ?? 'No reason was recorded.'}</AlertDescription>
        </Alert>
      )}

      {job.status === 'CANCELLED' && (
        <p className="text-[15.5px] text-[#98a5a1]">
          Cancelled at {job.progress}%. Nothing was kept: the partial output has been deleted.
        </p>
      )}

      {job.status === 'SUCCESS' &&
        (job.rows_total ? (
          <>
            <Stats job={job} />
            <button
              type="button"
              onClick={() => onPanelOpenChange(!panelOpen)}
              className="flex items-center gap-3 rounded-[12px] bg-[#0a0f0e] px-3.5 py-3 text-left transition-colors inset-ring inset-ring-[#151d1b] hover:bg-[#0e1312]"
            >
              <span className="tint flex size-8 shrink-0 items-center justify-center rounded-[9px] text-primary">
                <Table2 className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px]">{fileName(job.file_key)}</span>
                <span className="block text-[12px] text-dim">
                  Result · {(job.rows_total ?? 0).toLocaleString()} rows ·{' '}
                  {job.file_format === 'excel' ? 'from Excel' : 'from CSV'}
                </span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-dim" />
            </button>
          </>
        ) : (
          <p className="text-[15.5px] leading-relaxed text-[#98a5a1]">
            That file has a header and no rows, so there was nothing to change.
          </p>
        ))}

      {!isActive(job) && job.started_at && job.finished_at && (
        <p className="font-mono text-[11px] text-dim">
          {job.status === 'SUCCESS' ? 'Done' : 'Stopped'} in{' '}
          {duration(job.started_at, job.finished_at)}
          {job.attempts > 1 ? ` · ${job.attempts} attempts` : ''}
        </p>
      )}
    </div>
  )
}

/** The numbers, as the design shows numbers: big, mono, one line of caption. */
function Stats({ job }: { job: Job }) {
  const total = job.rows_total ?? 0
  const changed = job.rows_changed ?? 0
  const share = total ? Math.round((changed / total) * 100) : 0

  return (
    <div className="grid grid-cols-2 gap-2.5">
      {[
        { value: total.toLocaleString(), caption: 'rows processed', accent: false },
        { value: changed.toLocaleString(), caption: `rows changed · ${share}%`, accent: true },
      ].map((card) => (
        <div
          key={card.caption}
          className="flex flex-col gap-1.5 rounded-[12px] bg-[#0a0f0e] px-4 py-3.5 inset-ring inset-ring-[#151d1b]"
        >
          <span
            className={cn(
              'font-mono text-[26px] leading-none',
              card.accent ? 'text-primary' : 'text-[#e2eae7]',
            )}
          >
            {card.value}
          </span>
          <span className="text-[12px] text-dim">{card.caption}</span>
        </div>
      ))}
    </div>
  )
}

/** What Claude decided, for the two transformations it plans. */
function Report({ job }: { job: Job }) {
  const cached = job.report!.from_cache

  if (job.kind === 'standardise') {
    const report = job.report as StandardiseReport
    return (
      <section className="flex flex-col gap-2.5" aria-label="What was standardised">
        <p className="flex flex-wrap items-center gap-2 text-[15.5px] leading-relaxed text-[#cdd8d5]">
          <span>
            <span className="font-mono text-primary">{report.distinct_before}</span> different
            values in <span className="text-foreground">{report.column}</span> became{' '}
            <span className="font-mono text-primary">{report.distinct_after}</span>.
          </span>
          {cached && <CacheBadge />}
        </p>
        <ReportTable
          head={['Was', 'Became', 'Rows']}
          rows={report.mapping.map((entry) => [
            <span key="from" className="font-mono text-[12px] text-[#98a5a1]">
              {entry.from}
            </span>,
            entry.to,
            <span key="rows" className="font-mono text-[12px] text-dim tabular-nums">
              {entry.rows.toLocaleString()}
            </span>,
          ])}
          alignLast
        />
      </section>
    )
  }

  const report = job.report as PiiReport
  const placeholder = (kind: string) =>
    report.operations.find((operation) => operation.kind === kind)?.placeholder
  return (
    <section className="flex flex-col gap-2.5" aria-label="What was found">
      <p className="flex flex-wrap items-center gap-2 text-[15.5px] leading-relaxed text-[#cdd8d5]">
        <span>
          Claude saw column names and the shapes of values, never a value, and found personal data
          in {report.findings.length} place{report.findings.length === 1 ? '' : 's'}:
        </span>
        {cached && <CacheBadge />}
      </p>
      <ReportTable
        head={['Column', 'Holds', 'Because', 'Masked as']}
        rows={report.findings.map((finding) => [
          finding.column,
          <span key="kind" className="text-[#98a5a1]">
            {finding.kind.replace('_', ' ')}
          </span>,
          <span key="reason" className="text-dim">
            {finding.reason}
          </span>,
          <span key="placeholder" className="font-mono text-[12px] text-primary">
            {placeholder(finding.kind)}
          </span>,
        ])}
      />
      <p className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-dim">
        {report.operations.map((operation) => (
          <span key={operation.kind}>
            <span className="text-primary">{operation.placeholder}</span> in{' '}
            {operation.rows_changed === undefined
              ? '…'
              : operation.rows_changed.toLocaleString()}{' '}
            rows
          </span>
        ))}
      </p>
    </section>
  )
}

function ReportTable({
  head,
  rows,
  alignLast,
}: {
  head: string[]
  rows: ReactNode[][]
  alignLast?: boolean
}) {
  return (
    <div className="overflow-hidden rounded-[12px] bg-[#0a0f0e] inset-ring inset-ring-[#151d1b]">
      <table className="w-full text-[13px]">
        <thead className="text-left text-dim">
          <tr className="border-b border-rule">
            {head.map((label, index) => (
              <th
                key={label}
                className={cn(
                  'px-3.5 py-2 font-medium whitespace-nowrap',
                  alignLast && index === head.length - 1 && 'text-right',
                )}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-rule/60 last:border-0">
              {row.map((cell, index) => (
                <td
                  key={index}
                  className={cn(
                    'px-3.5 py-2',
                    alignLast && index === row.length - 1 && 'text-right',
                  )}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CacheBadge() {
  return (
    <span
      className="rounded-full bg-[#0e1312] px-2 py-0.5 font-mono text-[11px] text-dim inset-ring inset-ring-[#1b2422]"
      title="The same question was answered before, so Claude was not called this time."
    >
      from cache
    </span>
  )
}

/** A block of code with its own header, as the design has it. */
function CodeCard({ label, code, badge }: { label: string; code: string; badge?: string }) {
  const [copied, setCopied] = useState(false)

  return (
    <div className="overflow-hidden rounded-[12px] bg-[#0a0f0e] inset-ring inset-ring-[#151d1b]">
      <div className="flex items-center gap-2 border-b border-rule px-3.5 py-2">
        <span className="eyebrow text-dim">{label}</span>
        {badge && (
          <span className="tint rounded-full px-2 py-0.5 font-mono text-[10px] text-primary">
            {badge}
          </span>
        )}
        <button
          type="button"
          onClick={() => {
            navigator.clipboard?.writeText(code)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
          className="ml-auto flex items-center gap-1.5 text-[11px] text-dim transition-colors hover:text-foreground"
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto px-3.5 py-3 font-mono text-[12.5px] leading-relaxed text-[#cdd8d5]">
        {code}
      </pre>
    </div>
  )
}

function Unavailable({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="font-heading text-[28px] text-[#eef4f1]">{title}</h1>
      <p className="max-w-md text-[15.5px] leading-relaxed text-balance text-[#98a5a1]">{message}</p>
      <Button asChild>
        <Link href="/">New transformation</Link>
      </Button>
    </div>
  )
}
