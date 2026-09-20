import { useConnection } from '@/features/connection/api'
import { Link } from '@/components/link'
import { matchJobPath, usePath } from '@/lib/router'
import { cn, fileName } from '@/lib/utils'
import { useJobs } from './api'
import { StatusDot } from './status'

/** The sidebar's list of this connection's jobs. */
export function RecentJobs() {
  const { data: connection } = useConnection()
  const { data: jobs } = useJobs()
  const openJobId = matchJobPath(usePath())

  if (!connection || !jobs?.length) {
    return (
      <p className="px-2 text-sm text-muted-foreground/70">
        {connection ? 'Your transformations will appear here.' : 'Connect a bucket to see your transformations.'}
      </p>
    )
  }

  return (
    <ul className="-mx-1 flex min-h-0 flex-col gap-0.5 overflow-y-auto px-1">
      {jobs.map((job) => (
        <li key={job.id}>
          <Link
            href={`/jobs/${job.id}`}
            aria-current={job.id === openJobId ? 'page' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-sidebar-accent',
              job.id === openJobId && 'bg-sidebar-accent',
            )}
          >
            <StatusDot status={job.status} />
            <span className="min-w-0 flex-1">
              <span className="block truncate">{fileName(job.file_key)}</span>
              <span className={cn('block truncate text-xs text-muted-foreground', !job.prompt && 'font-mono')}>
                {job.prompt ?? job.pattern}
              </span>
            </span>
            {job.status === 'RUNNING' && (
              <span className="text-xs text-muted-foreground tabular-nums">{job.progress}%</span>
            )}
          </Link>
        </li>
      ))}
    </ul>
  )
}
