import { Link } from '@/components/link'
import { useConnection } from '@/features/connection/api'
import { matchJobPath, usePath } from '@/lib/router'
import { cn, fileName, since } from '@/lib/utils'
import { KIND_LABELS, useJobs } from './api'
import { StatusDot } from './status'

/** The sidebar's list of this connection's jobs. */
export function RecentJobs() {
  const { data: connection } = useConnection()
  const { data: jobs } = useJobs()
  const openJobId = matchJobPath(usePath())

  if (!connection || !jobs?.length) {
    return (
      <p className="px-2 py-1 text-[12px] leading-relaxed text-dim">
        {connection
          ? 'Your transformations will appear here.'
          : 'Connect a bucket to see your transformations.'}
      </p>
    )
  }

  return (
    <ul className="flex flex-col">
      {jobs.map((job) => {
        const open = job.id === openJobId
        return (
          <li key={job.id}>
            <Link
              href={`/jobs/${job.id}`}
              aria-current={open ? 'page' : undefined}
              className={cn(
                'relative flex items-start gap-2.5 rounded-[9px] px-2.5 py-2 transition-colors',
                open ? 'tint' : 'hover:bg-[#0e1312]',
              )}
            >
              <StatusDot status={job.status} className="mt-1.5" />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span
                  className={cn('truncate text-[13px]', open ? 'text-foreground' : 'text-[#d5dedb]')}
                >
                  {fileName(job.file_key)}
                </span>
                <span className="truncate text-[11px] text-dim">
                  {job.kind === 'replace'
                    ? (job.prompt ?? job.pattern)
                    : KIND_LABELS[job.kind]}{' '}
                  · {since(job.created_at)}
                </span>
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
