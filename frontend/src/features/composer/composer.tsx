import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  CircleAlert,
  Combine,
  EyeOff,
  FileSpreadsheet,
  FolderOpen,
  Plug,
  Regex,
  Replace,
  Sparkles,
  X,
} from 'lucide-react'

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
import { KIND_LABELS, submitJob, type JobKind, type JobRequest } from '@/features/jobs/api'
import { ApiError } from '@/lib/api'
import { navigate } from '@/lib/router'
import { cn, fileName, formatFileSize, shapeOf } from '@/lib/utils'
import { S3Dialog } from './s3-dialog'

type Mode = 'describe' | 'regex'

const KINDS: { kind: JobKind; icon: typeof Replace; needsModel: boolean }[] = [
  { kind: 'replace', icon: Replace, needsModel: false },
  { kind: 'redact_pii', icon: EyeOff, needsModel: true },
  { kind: 'standardise', icon: Combine, needsModel: true },
]

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
  const [chosenKind, setChosenKind] = useState<JobKind>('replace')
  const [chosenMode, setChosenMode] = useState<Mode>('describe')
  // One text per use: a sentence is not a regex, and neither is an instruction for standardising,
  // so switching must not carry one into the other.
  const [texts, setTexts] = useState({ describe: '', regex: '', standardise: '' })
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
  const kind: JobKind = describeAvailable ? chosenKind : 'replace'
  const mode: Mode = describeAvailable ? chosenMode : 'regex'
  const slot = kind === 'standardise' ? 'standardise' : mode
  const text = texts[slot]
  const setText = (value: string) => setTexts((current) => ({ ...current, [slot]: value }))
  const preview = usePreview(file?.key ?? null)

  function chooseKind(next: JobKind) {
    setChosenKind(next)
    setColumns([]) // what a chosen column means differs from one transformation to the next
    setError(null)
  }

  function chooseFile(next: S3File | null) {
    setChosenFile(next)
    setColumns([]) // another file has other columns
  }

  async function handleSubmit() {
    if (!file) return
    setSubmitting(true)
    setError(null)
    try {
      const target = { file_key: file.key, columns }
      const request: JobRequest =
        kind === 'redact_pii'
          ? { ...target, kind }
          : kind === 'standardise'
            ? { ...target, kind, ...(text.trim() ? { prompt: text.trim() } : {}) }
            : mode === 'describe'
              ? { ...target, replacement, prompt: text }
              : { ...target, replacement, pattern: text }
      const job = await submitJob(request)
      queryClient.setQueryData(['jobs', job.id], job)
      queryClient.invalidateQueries({ queryKey: ['jobs'], exact: true })
      navigate(`/jobs/${job.id}`)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'error', 'Something went wrong.'))
      setSubmitting(false)
    }
  }

  const ready =
    kind === 'replace' ? text.trim() !== '' : kind === 'standardise' ? columns.length === 1 : true
  const canSubmit = Boolean(file) && ready && !submitting
  // One real value from the preview and what a language model would be shown in its place.
  const example = preview.data?.status === 'done'
    ? preview.data.rows.flat().find((cell) => cell && /[@\d]/.test(cell) && cell.length > 7)
    : undefined

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
        <div className="flex flex-wrap justify-center gap-1.5" role="group" aria-label="Transformation">
          {KINDS.map(({ kind: option, icon: Icon, needsModel }) => (
            <Button
              key={option}
              variant={kind === option ? 'secondary' : 'ghost'}
              size="sm"
              className={cn('rounded-full', kind !== option && 'text-muted-foreground')}
              aria-pressed={kind === option}
              disabled={needsModel && !describeAvailable}
              title={
                needsModel && !describeAvailable
                  ? 'This server was started without an ANTHROPIC_API_KEY, and this needs a language model.'
                  : undefined
              }
              onClick={() => chooseKind(option)}
            >
              <Icon />
              {KIND_LABELS[option]}
            </Button>
          ))}
        </div>

        <PromptInput
          value={text}
          onValueChange={setText}
          onSubmit={handleSubmit}
          canSubmit={canSubmit}
          placeholder={
            kind === 'standardise'
              ? 'Optional: how should the values be written? For example: use full English country names'
              : mode === 'describe'
                ? "Describe what to find, for example: find email addresses in the Email column and replace them with 'REDACTED'"
                : String.raw`A regular expression, for example [\w.+-]+@[\w-]+\.[\w.]+`
          }
          inputClassName={
            kind === 'replace' && mode === 'regex' ? 'font-mono text-[0.95rem] md:text-[0.95rem]' : undefined
          }
          body={
            kind === 'redact_pii' ? (
              <p className="px-2 py-1.5 text-base text-muted-foreground">
                Claude works out which columns hold personal data, and Spark masks it:{' '}
                <span className="text-foreground">[EMAIL]</span>, <span className="text-foreground">[PHONE]</span>,{' '}
                <span className="text-foreground">[NAME]</span>. Nothing to type.
              </p>
            ) : undefined
          }
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

              {kind === 'replace' && (
              <>
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
              )}
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
                : kind === 'redact_pii'
                  ? example
                    ? `Claude is sent column names and the shape of a few values, never a value: “${example}” goes as “${shapeOf(example)}”.`
                    : 'Claude is sent column names and the shape of a few values (letters become a, digits become 9), never a value.'
                  : kind === 'standardise'
                    ? columns.length === 1
                      ? `The distinct values of “${columns[0]}” will be sent to Claude, 300 at most. A column with more is refused, not sent.`
                      : 'Click the one column to standardise. Its distinct values, and nothing else, will be sent to Claude.'
                    : mode === 'describe'
                      ? 'Claude writes the pattern, and it is checked before it runs. Only this sentence is sent, never your data.'
                      : 'The replacement is used as literal text. Press Enter to run.'}
          </p>
        )}
      </div>

      {file ? (
        <Preview
          fileKey={file.key}
          columns={columns}
          onColumnsChange={setColumns}
          kind={kind}
          describing={mode === 'describe'}
        />
      ) : (
        <div className="flex flex-wrap justify-center gap-2">
          {kind === 'replace' && SUGGESTIONS[mode].map((suggestion) => (
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
  kind: JobKind
  /** In Describe mode the sentence itself may name the columns. */
  describing: boolean
}

/** The file's first rows. Its column headers double as the column picker. */
function Preview({ fileKey, columns, onColumnsChange, kind, describing }: PreviewProps) {
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
    onColumnsChange(
      columns.includes(column)
        ? columns.filter((name) => name !== column)
        : kind === 'standardise'
          ? [column] // one column at a time: its values are what is sent
          : [...columns, column],
    )

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
        ) : kind === 'standardise' ? (
          'Click the header of the column to standardise.'
        ) : kind === 'redact_pii' ? (
          'Looks in every column. Click column headers to look in specific ones only.'
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
