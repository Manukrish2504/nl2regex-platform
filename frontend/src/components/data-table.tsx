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

/** A read-only grid of text cells: the file preview, and a page of a job's result. */
export function DataTable({
  columns,
  rows,
  highlighted = [],
  onToggleColumn,
  firstRowNumber = 1,
  className,
}: DataTableProps) {
  return (
    <div
      className={cn(
        'overflow-x-auto rounded-[12px] bg-card inset-ring inset-ring-border',
        className,
      )}
    >
      <table className="w-full border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-rule">
            <th className="w-0 px-3 py-2 text-right font-mono text-[10px] font-normal text-dim">
              #
            </th>
            {columns.map((column) => {
              const active = highlighted.includes(column)
              return (
                <th
                  key={column}
                  className={cn(
                    'px-3 py-2 text-left text-[12px] font-medium whitespace-nowrap',
                    active ? 'text-primary' : 'text-muted-foreground',
                  )}
                >
                  {onToggleColumn ? (
                    <button
                      type="button"
                      aria-pressed={active}
                      onClick={() => onToggleColumn(column)}
                      className={cn(
                        '-mx-1.5 rounded-md px-1.5 py-0.5 transition-colors',
                        active ? 'tint' : 'hover:bg-rule',
                      )}
                    >
                      {column}
                    </button>
                  ) : (
                    column
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-rule/50 last:border-0">
              <td className="px-3 py-1.5 text-right font-mono text-[10px] text-dim tabular-nums">
                {(firstRowNumber + rowIndex).toLocaleString()}
              </td>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className={cn(
                    'max-w-[22rem] truncate px-3 py-1.5',
                    highlighted.includes(columns[cellIndex]) ? 'text-foreground' : 'text-muted-foreground',
                  )}
                  title={cell ?? undefined}
                >
                  {cell ?? <span className="text-faint italic">empty</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
