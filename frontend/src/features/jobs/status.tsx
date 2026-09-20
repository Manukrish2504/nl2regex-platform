import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { JobStatus } from './api'

const LABELS: Record<JobStatus, string> = {
  QUEUED: 'Queued',
  RUNNING: 'Running',
  SUCCESS: 'Done',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
}

const DOT_COLOURS: Record<JobStatus, string> = {
  QUEUED: 'bg-muted-foreground',
  RUNNING: 'bg-primary animate-pulse',
  SUCCESS: 'bg-primary',
  FAILED: 'bg-destructive',
  CANCELLED: 'bg-muted-foreground/50',
}

export function StatusDot({ status }: { status: JobStatus }) {
  return (
    <span
      className={cn('size-2 shrink-0 rounded-full', DOT_COLOURS[status])}
      role="img"
      aria-label={LABELS[status]}
    />
  )
}

export function StatusBadge({ status }: { status: JobStatus }) {
  const variant =
    status === 'FAILED' ? 'destructive' : status === 'RUNNING' || status === 'SUCCESS' ? 'default' : 'secondary'
  return <Badge variant={variant}>{LABELS[status]}</Badge>
}
