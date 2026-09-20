import { useState } from 'react'
import { ChevronLeft, ChevronRight, CircleAlert, X } from 'lucide-react'

import { DataTable } from '@/components/data-table'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, fileName, resolveColumns } from '@/lib/utils'
import { useJobRows, type Job, type PiiReport } from './api'

const PAGE_SIZES = [25, 50, 100]

/** The columns a job changed, or null for "every column". */
function touchedColumns(job: Job): string[] | null {
  if (job.kind === 'redact_pii' && job.report) {
    return (job.report as PiiReport).operations.flatMap((operation) => operation.columns)
  }
  return job.columns.length ? job.columns : null
}

/**
 * The result, docked beside the conversation: the rows a page at a time, read straight from the
 * Parquet the job wrote. It is a panel and not a message, because it is millions of rows long.
 */
export function ResultsPanel({ job, onClose }: { job: Job; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0])
  const rows = useJobRows(job.id, page, pageSize, job.status === 'SUCCESS')

  const total = job.rows_total ?? 0
  const lastPage = Math.max(1, Math.ceil(total / pageSize))
  const first = (page - 1) * pageSize + 1

  return (
    <aside className="absolute inset-0 z-20 flex flex-col bg-[#080b0a] lg:static lg:z-0 lg:w-[46%] lg:max-w-[720px] lg:shrink-0 lg:border-l lg:border-rule">
      <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-rule px-4">
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-[13px] text-[#e8efec]">{fileName(job.file_key)}</p>
          <p className="truncate text-[11px] text-dim">
            Result · {total.toLocaleString()} rows ·{' '}
            {(job.rows_changed ?? 0).toLocaleString()} changed
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close the results">
          <X className="size-4" />
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {rows.isError ? (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>{rows.error.message}</AlertDescription>
          </Alert>
        ) : rows.data ? (
          rows.data.rows.length ? (
            <DataTable
              columns={rows.data.columns}
              rows={rows.data.rows}
              highlighted={resolveColumns(touchedColumns(job) ?? rows.data.columns, rows.data.columns)}
              firstRowNumber={(rows.data.page - 1) * rows.data.page_size + 1}
              className={cn(rows.isPlaceholderData && 'opacity-60 transition-opacity')}
            />
          ) : (
            <p className="px-1 py-6 text-center text-[13px] text-dim">
              This page is past the end of the result.
            </p>
          )
        ) : (
          <Skeleton className="h-64 w-full rounded-[12px]" />
        )}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center gap-3 border-t border-rule px-4 py-2.5 text-[12px]">
        <span className="font-mono text-[11px] text-dim tabular-nums">
          {total
            ? `${first.toLocaleString()}–${Math.min(page * pageSize, total).toLocaleString()} of ${total.toLocaleString()}`
            : 'no rows'}
        </span>
        <label className="ml-auto flex items-center gap-2 text-dim">
          Rows
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value))
              setPage(1)
            }}
            className="h-7 rounded-[8px] bg-[#0e1312] px-2 font-mono text-[11px] text-foreground inset-ring inset-ring-[#1b2422] outline-none"
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setPage(page - 1)}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="font-mono text-[11px] text-dim tabular-nums">
            {page.toLocaleString()} / {lastPage.toLocaleString()}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setPage(page + 1)}
            disabled={page >= lastPage}
            aria-label="Next page"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </footer>
    </aside>
  )
}
