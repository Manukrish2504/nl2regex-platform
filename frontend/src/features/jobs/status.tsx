import { cn } from '@/lib/utils'
import type { JobStatus } from './api'

const COLOURS: Record<JobStatus, string> = {
  QUEUED: 'bg-dim',
  RUNNING: 'bg-primary',
  SUCCESS: 'bg-primary',
  FAILED: 'bg-destructive',
  CANCELLED: 'bg-dim',
}

const WORDS: Record<JobStatus, string> = {
  QUEUED: 'Queued',
  RUNNING: 'Running',
  SUCCESS: 'Done',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
}

/** A job's state as one dot, for a list. It pulses while the job is running. */
export function StatusDot({ status, className }: { status: JobStatus; className?: string }) {
  return (
    <span
      className={cn(
        'size-[7px] shrink-0 rounded-full',
        COLOURS[status],
        status === 'RUNNING' && 'animate-pulse',
        className,
      )}
      role="img"
      aria-label={WORDS[status]}
      title={WORDS[status]}
    />
  )
}

/** The same, with the word beside it. */
export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={cn(
        'flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[11px]',
        status === 'FAILED'
          ? 'bg-destructive/10 text-destructive'
          : status === 'SUCCESS' || status === 'RUNNING'
            ? 'tint text-primary'
            : 'bg-muted text-dim inset-ring inset-ring-input',
      )}
    >
      <StatusDot status={status} />
      {WORDS[status]}
    </span>
  )
}
