import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, FileSpreadsheet, FolderOpen, Plug, Regex, Sparkles, X } from 'lucide-react'

import { DataTable } from '@/components/data-table'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PromptInput } from '@/components/ui/prompt-input'
import { Skeleton } from '@/components/ui/skeleton'
import { useConfig } from '@/features/config/api'
import { useConnection } from '@/features/connection/api'
import { usePreview, type S3File } from '@/features/files/api'
import { submitJob } from '@/features/jobs/api'
import { ApiError } from '@/lib/api'
import { navigate } from '@/lib/router'
import { fileName, formatFileSize } from '@/lib/utils'
import { S3Dialog } from './s3-dialog'

type Mode = 'describe' | 'regex'

// A sentence may carry its own replacement ("... and replace them with REDACTED"), so in Describe
// mode a suggestion fills in the sentence alone and leaves the replacement field empty.
const SUGGESTIONS: Record<Mode, { label: string; text: string; replacement: string }[]> = {
  describe: [
    { label: 'Redact email addresses', text: "Find email addresses and replace them with 'REDACTED'.", replacement: '' },
    { label: 'Remove phone numbers', text: 'Remove phone numbers', replacement: '' },
    { label: 'Mask card numbers', text: 'Replace credit card numbers with ****', replacement: '' },
  ],
  regex: [
    { label: 'Email addresses → REDACTED', text: String.raw`[\w.+-]+@[\w-]+\.[\w.]+`, replacement: 'REDACTED' },
    { label: 'Phone numbers → ***', text: String.raw`\+?\d[\d\s().-]{7,}\d`, replacement: '***' },
    { label: 'Remove URLs', text: String.raw`https?://\S+`, replacement: '' },
  ],
}

/** The landing screen: choose a file, say what to find and what to put in its place, and run it. */
export function Composer() {
  const queryClient = useQueryClient()
  const { data: connection, isPending } = useConnection()
  const { data: config } = useConfig()
  const [chosenMode, setChosenMode] = useState<Mode>('describe')
  // One text per mode: a sentence is not a regex, so switching must not carry one into the other.
  const [texts, setTexts] = useState<Record<Mode, string>>({ describe: '', regex: '' })
  const [replacement, setReplacement] = useState('')
  const [columns, setColumns] = useState<string[]>([])
  const [chosenFile, setChosenFile] = useState<S3File | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  // A file belongs to a connection. When the connection goes, so does the choice.
  const file = connection ? chosenFile : null
  // A server started without an API key has no language model, and then only a regex can be run.
  const describeAvailable = config?.describe_available ?? false
  const mode: Mode = describeAvailable ? chosenMode : 'regex'
  const text = texts[mode]
  const setText = (value: string) => setTexts((current) => ({ ...current, [mode]: value }))

  function chooseFile(next: S3File | null) {
    setChosenFile(next)
    setColumns([]) // another file has other columns
  }

  async function handleSubmit() {
    if (!file) return
    setSubmitting(true)
    setError(null)
    try {
      const request = { file_key: file.key, replacement, columns }
      const job = await submitJob(mode === 'describe' ? { ...request, prompt: text } : { ...request, pattern: text })
      queryClient.setQueryData(['jobs', job.id], job)
      queryClient.invalidateQueries({ queryKey: ['jobs'], exact: true })
      navigate(`/jobs/${job.id}`)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'error', 'Something went wrong.'))
      setSubmitting(false)
    }
  }

  const canSubmit = Boolean(file) && text.trim() !== '' && !submitting

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
          Connect your S3 bucket, pick a CSV or Excel file, and say what to find and what to replace it
          with.
        </p>
      </div>

      <div className="flex w-full flex-col gap-3">
        <PromptInput
          value={text}
          onValueChange={setText}
          onSubmit={handleSubmit}
          canSubmit={canSubmit}
          placeholder={
            mode === 'describe'
              ? "Describe what to find, for example: find email addresses in the Email column and replace them with 'REDACTED'"
              : String.raw`A regular expression, for example [\w.+-]+@[\w-]+\.[\w.]+`
          }
          inputClassName={mode === 'regex' ? 'font-mono text-[0.95rem] md:text-[0.95rem]' : undefined}
          attachments={
            file && (
              <div className="flex items-center gap-2 rounded-xl border border-border bg-muted/60 py-1.5 pr-1.5 pl-3 text-sm">
                <FileSpreadsheet className="size-4 shrink-0 text-primary" />
                <span className="max-w-64 truncate font-medium" title={file.key}>
                  {fileName(file.key)}
                </span>
                <span className="text-xs text-muted-foreground">{formatFileSize(file.size)}</span>
                <Badge variant="secondary">{file.format === 'excel' ? 'XLSX' : 'CSV'}</Badge>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="rounded-full"
                  aria-label="Remove file"
                  onClick={() => chooseFile(null)}
                >
                  <X />
                </Button>
              </div>
            )
          }
          actions={
            <>
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

              <div className="flex rounded-full border border-border p-0.5" role="group" aria-label="How to give the pattern">
                <Button
                  variant={mode === 'describe' ? 'secondary' : 'ghost'}
                  size="xs"
                  className="rounded-full"
                  aria-pressed={mode === 'describe'}
                  disabled={!describeAvailable}
                  title={
                    describeAvailable
                      ? 'Say what to find in plain English. Claude writes the pattern.'
                      : 'This server was started without an ANTHROPIC_API_KEY, so patterns must be typed.'
                  }
                  onClick={() => setChosenMode('describe')}
                >
                  <Sparkles />
                  Describe
                </Button>
                <Button
                  variant={mode === 'regex' ? 'secondary' : 'ghost'}
                  size="xs"
                  className="rounded-full"
                  aria-pressed={mode === 'regex'}
                  onClick={() => setChosenMode('regex')}
                >
                  <Regex />
                  Regex
                </Button>
              </div>

              <label className="flex min-w-40 flex-1 items-center gap-2 text-sm text-muted-foreground sm:max-w-72">
                <span className="shrink-0">Replace with</span>
                <Input
                  value={replacement}
                  onChange={(event) => setReplacement(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.nativeEvent.isComposing && canSubmit) handleSubmit()
                  }}
                  placeholder={mode === 'describe' ? 'from your sentence' : 'nothing (removes matches)'}
                  className="h-7 rounded-full font-mono text-[0.8rem] md:text-[0.8rem]"
                  spellCheck={false}
                />
              </label>
            </>
          }
        />

        {error ? (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : (
          <p className="text-center text-xs text-muted-foreground">
            {!connection
              ? 'Connect a bucket and choose a file to begin.'
              : !file
                ? 'Choose a file to begin.'
                : mode === 'describe'
                  ? 'Claude writes the pattern, and it is checked before it runs. Only this sentence is sent, never your data.'
                  : 'The replacement is used as literal text. Press Enter to run.'}
          </p>
        )}
      </div>

      {file ? (
        <Preview fileKey={file.key} columns={columns} onColumnsChange={setColumns} describing={mode === 'describe'} />
      ) : (
        <div className="flex flex-wrap justify-center gap-2">
          {SUGGESTIONS[mode].map((suggestion) => (
            <Button
              key={suggestion.label}
              variant="outline"
              size="sm"
              className="h-auto rounded-full px-3 py-1.5 text-muted-foreground"
              onClick={() => {
                setText(suggestion.text)
                setReplacement(suggestion.replacement)
              }}
            >
              {suggestion.label}
            </Button>
          ))}
        </div>
      )}

      <S3Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSelect={(selected) => {
          chooseFile(selected)
          setDialogOpen(false)
        }}
      />
    </section>
  )
}

interface PreviewProps {
  fileKey: string
  columns: string[]
  onColumnsChange: (columns: string[]) => void
  /** In Describe mode the sentence itself may name the columns. */
  describing: boolean
}

/** The file's first rows. Its column headers double as the column picker. */
function Preview({ fileKey, columns, onColumnsChange, describing }: PreviewProps) {
  const preview = usePreview(fileKey)

  if (preview.isError || preview.data?.status === 'failed') {
    const message =
      preview.data?.status === 'failed' ? preview.data.error.message : (preview.error?.message ?? '')
    return (
      <Alert variant="destructive" className="w-full">
        <CircleAlert />
        <AlertDescription>Could not read this file. {message}</AlertDescription>
      </Alert>
    )
  }
  if (preview.data?.status !== 'done') {
    return (
      <div className="flex w-full flex-col gap-2" aria-label="Reading the file">
        <p className="text-sm text-muted-foreground">Reading the first rows…</p>
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  const toggle = (column: string) =>
    onColumnsChange(columns.includes(column) ? columns.filter((name) => name !== column) : [...columns, column])

  return (
    <div className="flex w-full flex-col gap-2">
      <p className="text-sm text-muted-foreground">
        {columns.length ? (
          <>
            Applies to <span className="font-medium text-foreground">{columns.join(', ')}</span>.{' '}
            <button type="button" className="underline underline-offset-4 hover:text-foreground" onClick={() => onColumnsChange([])}>
              Use every column
            </button>
          </>
        ) : describing ? (
          'Applies to the columns your sentence names, or to every column if it names none. Click column headers to choose them yourself.'
        ) : (
          'Applies to every column. Click column headers to choose specific ones.'
        )}
      </p>
      <DataTable
        columns={preview.data.columns}
        rows={preview.data.rows}
        highlighted={columns}
        onToggleColumn={toggle}
      />
      <p className="text-xs text-muted-foreground">The first {preview.data.rows.length} rows of the file.</p>
    </div>
  )
}
