import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

interface DataTableProps {
  columns: string[]
  rows: (string | null)[][]
  /** Columns drawn as targets of the transformation. */
  highlighted?: string[]
  /** When given, column headers become toggle buttons. */
  onToggleColumn?: (column: string) => void
  /** The number shown beside the first row, for tables that are one page of something larger. */
  firstRowNumber?: number
  className?: string
}

/** A read-only grid of text cells, used for the file preview and for a job's results. */
export function DataTable({
  columns,
  rows,
  highlighted = [],
  onToggleColumn,
  firstRowNumber = 1,
  className,
}: DataTableProps) {
  return (
    <div className={cn('overflow-hidden rounded-xl border border-border bg-card/60', className)}>
      <Table>
        <TableHeader className="bg-muted/40">
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-0 text-right text-xs text-muted-foreground">#</TableHead>
            {columns.map((column) => {
              const active = highlighted.includes(column)
              return (
                <TableHead key={column} className={cn('whitespace-nowrap', active && 'text-primary')}>
                  {onToggleColumn ? (
                    <button
                      type="button"
                      aria-pressed={active}
                      onClick={() => onToggleColumn(column)}
                      className={cn(
                        '-mx-1.5 rounded-md px-1.5 py-0.5 font-medium transition-colors hover:bg-muted',
                        active && 'bg-primary/15 hover:bg-primary/25',
                      )}
                    >
                      {column}
                    </button>
                  ) : (
                    column
                  )}
                </TableHead>
              )
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, rowIndex) => (
            <TableRow key={rowIndex}>
              <TableCell className="text-right text-xs text-muted-foreground tabular-nums">
                {(firstRowNumber + rowIndex).toLocaleString()}
              </TableCell>
              {row.map((cell, cellIndex) => (
                <TableCell
                  key={cellIndex}
                  title={cell ?? undefined}
                  className={cn(
                    'max-w-72 truncate',
                    highlighted.includes(columns[cellIndex]) && 'bg-primary/5',
                  )}
                >
                  {cell ?? <span className="text-muted-foreground/50">empty</span>}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">No rows.</p>
      )}
    </div>
  )
}
