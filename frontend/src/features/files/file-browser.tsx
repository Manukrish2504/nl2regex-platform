import { useState } from 'react'
import { ChevronRight, CircleAlert, FileSpreadsheet, FileText, Folder, LoaderCircle } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatFileSize } from '@/lib/utils'
import { useFiles, type S3File } from './api'

const FORMAT_LABELS = { csv: 'CSV', excel: 'XLSX' } as const

const ROW = 'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm'

interface FileBrowserProps {
  bucket: string
  onSelect: (file: S3File) => void
}

export function FileBrowser({ bucket, onSelect }: FileBrowserProps) {
  const [prefix, setPrefix] = useState('')
  const listing = useFiles(prefix)

  const pages = listing.data?.pages ?? []
  const folders = pages.flatMap((page) => page.folders)
  const files = pages.flatMap((page) => page.files)

  // "samples/archive/" becomes crumbs for "samples/" and "samples/archive/".
  const parts = prefix.split('/').filter(Boolean)
  const crumbs = parts.map((name, index) => ({ name, prefix: `${parts.slice(0, index + 1).join('/')}/` }))

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <nav aria-label="Folder path" className="flex flex-wrap items-center gap-1 text-sm">
        <Button variant="ghost" size="sm" onClick={() => setPrefix('')}>
          {bucket}
        </Button>
        {crumbs.map((crumb) => (
          <span key={crumb.prefix} className="flex items-center gap-1">
            <ChevronRight className="size-3.5 text-muted-foreground" />
            <Button variant="ghost" size="sm" onClick={() => setPrefix(crumb.prefix)}>
              {crumb.name}
            </Button>
          </span>
        ))}
      </nav>

      <div className="-mx-1 max-h-[50vh] min-h-40 overflow-y-auto px-1">
        {listing.isPending && (
          <div className="flex flex-col gap-2 p-1" aria-label="Loading files">
            {[0, 1, 2, 3].map((row) => (
              <Skeleton key={row} className="h-9 w-full" />
            ))}
          </div>
        )}

        {listing.isError && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription className="flex items-center justify-between gap-3">
              {listing.error.message}
              <Button variant="outline" size="sm" onClick={() => listing.refetch()}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {listing.isSuccess && folders.length === 0 && files.length === 0 && (
          <p className="px-3 py-10 text-center text-sm text-muted-foreground">This folder is empty.</p>
        )}

        <ul className="flex flex-col">
          {folders.map((folder) => (
            <li key={folder}>
              <button type="button" className={`${ROW} hover:bg-muted`} onClick={() => setPrefix(folder)}>
                <Folder className="size-4 shrink-0 text-primary" />
                <span className="truncate">{folder.slice(prefix.length, -1)}</span>
                <ChevronRight className="ml-auto size-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          ))}
          {files.map((file) => {
            const FileIcon = file.format ? FileSpreadsheet : FileText
            return (
              <li key={file.key}>
                <button
                  type="button"
                  className={`${ROW} enabled:hover:bg-muted disabled:cursor-not-allowed disabled:opacity-45`}
                  disabled={!file.format}
                  title={file.format ? undefined : 'Only CSV and Excel (.xlsx) files can be processed'}
                  onClick={() => onSelect(file)}
                >
                  <FileIcon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">{file.key.slice(prefix.length)}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
                    {formatFileSize(file.size)} · {new Date(file.last_modified).toLocaleDateString()}
                  </span>
                  {file.format ? (
                    <Badge variant="secondary">{FORMAT_LABELS[file.format]}</Badge>
                  ) : (
                    <Badge variant="outline">Unsupported</Badge>
                  )}
                </button>
              </li>
            )
          })}
        </ul>

        {listing.hasNextPage && (
          <Button
            variant="ghost"
            className="mt-2 w-full"
            onClick={() => listing.fetchNextPage()}
            disabled={listing.isFetchingNextPage}
          >
            {listing.isFetchingNextPage && <LoaderCircle className="animate-spin" />}
            Load more
          </Button>
        )}
      </div>
    </div>
  )
}
