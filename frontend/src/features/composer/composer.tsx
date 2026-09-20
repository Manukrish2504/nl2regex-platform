import { useState } from 'react'
import { FileSpreadsheet, FolderOpen, Plug, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PromptInput } from '@/components/ui/prompt-input'
import { useConnection } from '@/features/connection/api'
import type { S3File } from '@/features/files/api'
import { formatFileSize } from '@/lib/utils'
import { S3Dialog } from './s3-dialog'

const SUGGESTIONS = [
  "Find email addresses in the email column and replace them with 'REDACTED'",
  'Mask every phone number with ***',
  'Remove email addresses hidden in the notes column',
]

/** The landing screen: say what to change, in which file. */
export function Composer() {
  const { data: connection, isPending } = useConnection()
  const [prompt, setPrompt] = useState('')
  const [chosenFile, setChosenFile] = useState<S3File | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  // A file belongs to a connection. When the connection goes, so does the choice.
  const file = connection ? chosenFile : null

  return (
    <section className="flex w-full flex-col items-center gap-8">
      <div className="flex flex-col items-center gap-3 text-center">
        <h1 className="text-4xl font-medium tracking-tight text-balance sm:text-5xl">
          Describe a pattern.{' '}
          <span className="bg-linear-to-r from-primary to-sky-400 bg-clip-text text-transparent">
            Transform millions of rows.
          </span>
        </h1>
        <p className="max-w-xl text-balance text-muted-foreground">
          Connect your S3 bucket, pick a CSV or Excel file, and say in plain English what to find and
          what to replace it with.
        </p>
      </div>

      <div className="flex w-full flex-col gap-3">
        <PromptInput
          value={prompt}
          onValueChange={setPrompt}
          onSubmit={() => undefined}
          // Running a transformation needs the job pipeline, which the next phase adds.
          canSubmit={false}
          placeholder="Describe what to find, and what to replace it with…"
          attachments={
            file && (
              <div className="flex items-center gap-2 rounded-xl border border-border bg-muted/60 py-1.5 pr-1.5 pl-3 text-sm">
                <FileSpreadsheet className="size-4 shrink-0 text-primary" />
                <span className="max-w-64 truncate font-medium" title={file.key}>
                  {file.key.split('/').pop()}
                </span>
                <span className="text-xs text-muted-foreground">{formatFileSize(file.size)}</span>
                <Badge variant="secondary">{file.format === 'excel' ? 'XLSX' : 'CSV'}</Badge>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="rounded-full"
                  aria-label="Remove file"
                  onClick={() => setChosenFile(null)}
                >
                  <X />
                </Button>
              </div>
            )
          }
          actions={
            <Button
              variant={!connection ? 'default' : file ? 'ghost' : 'outline'}
              size="sm"
              className="rounded-full"
              disabled={isPending}
              onClick={() => setDialogOpen(true)}
            >
              {connection ? <FolderOpen /> : <Plug />}
              {!connection ? 'Connect S3 bucket' : file ? 'Change file' : 'Choose file'}
            </Button>
          }
        />
        <p className="text-center text-xs text-muted-foreground">
          {file
            ? 'File ready. Running the transformation arrives with the job pipeline.'
            : 'Connect a bucket and choose a file to begin.'}
        </p>
      </div>

      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <Button
            key={suggestion}
            variant="outline"
            size="sm"
            className="h-auto rounded-full px-3 py-1.5 text-muted-foreground"
            onClick={() => setPrompt(suggestion)}
          >
            {suggestion}
          </Button>
        ))}
      </div>

      <S3Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSelect={(selected) => {
          setChosenFile(selected)
          setDialogOpen(false)
        }}
      />
    </section>
  )
}
