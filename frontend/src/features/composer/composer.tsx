import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowUp,
  ChevronRight,
  CircleAlert,
  Combine,
  EyeOff,
  FileSpreadsheet,
  Plus,
  Regex,
  Replace,
  Sparkles,
  X,
} from 'lucide-react'

import { DataTable } from '@/components/data-table'
import { Diamond } from '@/components/diamond'
import { Link } from '@/components/link'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useConfig } from '@/features/config/api'
import { useConnection } from '@/features/connection/api'
import { usePreview, type S3File } from '@/features/files/api'
import { isActive, submitJob, useJobs, type JobKind, type JobRequest } from '@/features/jobs/api'
import { StatusDot } from '@/features/jobs/status'
import { ApiError } from '@/lib/api'
import { navigate } from '@/lib/router'
import { cn, fileName, formatFileSize, shapeOf, since } from '@/lib/utils'
import { S3Dialog } from './s3-dialog'

type Mode = 'describe' | 'regex'

const KINDS: {
  kind: JobKind
  icon: typeof Replace
  title: string
  caption: string
  needsModel: boolean
}[] = [
  {
    kind: 'replace',
    icon: Replace,
    title: 'Find and replace',
    caption: 'Describe a pattern, or write the regex',
    needsModel: false,
  },
  {
    kind: 'redact_pii',
    icon: EyeOff,
    title: 'Redact personal data',
    caption: 'Found for you, masked by Spark',
    needsModel: true,
  },
  {
    kind: 'standardise',
    icon: Combine,
    title: 'Standardise a column',
    caption: 'One value per spelling',
    needsModel: true,
  },
]

// A suggestion fills the box. In Describe mode the sentence may carry its own replacement.
const SUGGESTIONS: Record<Mode, { label: string; text: string; replacement: string }[]> = {
  describe: [
    {
      label: 'Redact email addresses',
      text: "Find email addresses and replace them with 'REDACTED'.",
      replacement: '',
    },
    { label: 'Remove phone numbers', text: 'Remove phone numbers', replacement: '' },
    { label: 'Mask card numbers', text: 'Replace credit card numbers with ****', replacement: '' },
  ],
  regex: [
    { label: 'Email addresses', text: String.raw`[\w.+-]+@[\w-]+\.[\w.]+`, replacement: 'REDACTED' },
    { label: 'Phone numbers', text: String.raw`\+?\d[\d\s().-]{7,}\d`, replacement: '***' },
    { label: 'URLs', text: String.raw`https?://\S+`, replacement: '' },
  ],
}

interface ComposerProps {
  dialogOpen: boolean
  onDialogOpenChange: (open: boolean) => void
}

/** The home screen: choose a file, say what to do, and run it. */
export function Composer({ dialogOpen, onDialogOpenChange }: ComposerProps) {
  const queryClient = useQueryClient()
  const { data: connection, isPending } = useConnection()
  const { data: config } = useConfig()
  const { data: jobs } = useJobs()
  const [chosenKind, setChosenKind] = useState<JobKind>('replace')
  const [chosenMode, setChosenMode] = useState<Mode>('describe')
  const [texts, setTexts] = useState({ describe: '', regex: '', standardise: '' })
  const [replacement, setReplacement] = useState('')
  const [columns, setColumns] = useState<string[]>([])
  const [chosenFile, setChosenFile] = useState<S3File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  // A file belongs to a connection. When the connection goes, so does the choice.
  const file = connection ? chosenFile : null
  const describeAvailable = config?.describe_available ?? false
  const kind: JobKind = describeAvailable ? chosenKind : 'replace'
  const mode: Mode = describeAvailable ? chosenMode : 'regex'
  const slot = kind === 'standardise' ? 'standardise' : mode
  const text = texts[slot]
  const setText = (value: string) => setTexts((current) => ({ ...current, [slot]: value }))
  const preview = usePreview(file?.key ?? null)

  function chooseFile(next: S3File | null) {
    setChosenFile(next)
    setColumns([]) // another file has other columns
  }

  function chooseKind(next: JobKind) {
    setChosenKind(next)
    setColumns([]) // what a chosen column means differs from one transformation to the next
    setError(null)
  }

  const ready =
    Boolean(file) &&
    (kind === 'replace' ? text.trim() !== '' : kind === 'standardise' ? columns.length === 1 : true)
  const canSubmit = ready && !submitting

  async function handleSubmit() {
    if (!file || !canSubmit) return
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
      setError(
        caught instanceof ApiError ? caught : new ApiError(0, 'error', 'Something went wrong.'),
      )
      setSubmitting(false)
    }
  }

  /** What to do next, or what will be sent to Claude before it is sent. */
  function hint() {
    if (!connection) return 'Connect a bucket and choose a file to begin.'
    if (!file) return 'Choose a file to begin.'
    if (kind === 'redact_pii') {
      const rows = preview.data?.status === 'done' ? preview.data.rows : []
      const example = rows.flat().find((cell) => cell && /[@\d]/.test(cell) && cell.length > 7)
      const shown = example ? `: “${example}” goes as “${shapeOf(example)}”` : ''
      return `Only column names and the shape of a few values are sent, never a value${shown}.`
    }
    if (kind === 'standardise') {
      return columns.length === 1
        ? `The distinct values of “${columns[0]}” are sent, 300 at most. A column with more is refused, not sent.`
        : 'Click the one column to standardise. Its distinct values, and nothing else, are sent.'
    }
    return mode === 'describe'
      ? 'The pattern is written for you and checked before it runs. Only this sentence is sent, never your data.'
      : 'The replacement is used as literal text. Press Enter to run.'
  }

  const recent = (jobs ?? []).slice(0, 3)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[780px] flex-col gap-7 px-6 pt-[7vh] pb-16">
        <header className="flex flex-col gap-3">
          <p className="eyebrow flex items-center gap-2 text-dim">
            <Diamond className="text-primary" />
            {connection ? `${connection.bucket} · ${connection.region}` : 'Not connected'}
            {jobs?.some(isActive) ? ' · 1 running' : ''}
          </p>
          <h1 className="font-heading text-[34px] leading-[1.08] tracking-[-0.015em] text-foreground">
            Clean a spreadsheet the size of a warehouse.
          </h1>
          <p className="max-w-[46ch] text-[15.5px] leading-relaxed text-muted-foreground">
            Point at a CSV or Excel file in your own S3 bucket, say what to change in plain English,
            and a Spark job rewrites every row.
          </p>
        </header>

        {/* The composer: the file as a chip, the request, and the controls under it. */}
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-col gap-2.5 rounded-[14px] bg-popover p-3 shadow-[inset_0_0_0_1px_var(--surface-edge),0_8px_24px_-12px_rgba(0,0,0,0.8)]">
            {file && (
              <div className="flex items-center gap-2 self-start rounded-[10px] bg-muted py-1.5 pr-1.5 pl-2.5 text-[12px] inset-ring inset-ring-input">
                <FileSpreadsheet className="size-3.5 shrink-0 text-primary" />
                <span className="max-w-56 truncate" title={file.key}>
                  {fileName(file.key)}
                </span>
                <span className="font-mono text-[11px] text-dim">{formatFileSize(file.size)}</span>
                <button
                  type="button"
                  aria-label="Remove file"
                  onClick={() => chooseFile(null)}
                  className="rounded-md p-0.5 text-dim transition-colors hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              </div>
            )}

            {kind === 'redact_pii' ? (
              <p className="px-1 py-2 text-[15.5px] text-muted-foreground">
                nl2regex works out which columns hold personal data, and Spark masks it:{' '}
                <span className="font-mono text-[13px] text-foreground">[EMAIL]</span>{' '}
                <span className="font-mono text-[13px] text-foreground">[PHONE]</span>{' '}
                <span className="font-mono text-[13px] text-foreground">[NAME]</span>. Nothing to
                type.
              </p>
            ) : (
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
                    return
                  }
                  event.preventDefault()
                  handleSubmit()
                }}
                rows={2}
                spellCheck={kind !== 'replace' || mode === 'describe'}
                placeholder={
                  kind === 'standardise'
                    ? 'Optional: how should the values be written? For example, use full English country names'
                    : mode === 'describe'
                      ? 'What should change? For example: find email addresses in the Email column and replace them with REDACTED'
                      : String.raw`A regular expression, for example [\w.+-]+@[\w-]+\.[\w.]+`
                }
                aria-label="What should change"
                className={cn(
                  'field-sizing-content max-h-[40vh] w-full resize-none bg-transparent px-1 py-1.5 text-[15.5px] text-foreground outline-none placeholder:text-dim',
                  kind === 'replace' && mode === 'regex' && 'font-mono text-[13px]',
                )}
              />
            )}

            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                variant="ghost"
                size="icon-sm"
                className="rounded-[10px] text-dim"
                disabled={isPending}
                aria-label={file ? 'Change file' : 'Choose a file'}
                title={file ? 'Change file' : 'Choose a file'}
                onClick={() => onDialogOpenChange(true)}
              >
                <Plus className="size-4" />
              </Button>

              {kind === 'replace' && describeAvailable && (
                <div
                  className="flex rounded-full bg-muted p-0.5 inset-ring inset-ring-input"
                  role="group"
                  aria-label="How to give the pattern"
                >
                  {(['describe', 'regex'] as Mode[]).map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={mode === option}
                      onClick={() => setChosenMode(option)}
                      className={cn(
                        'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] transition-colors',
                        mode === option ? 'tint text-primary' : 'text-dim hover:text-foreground',
                      )}
                    >
                      {option === 'describe' ? (
                        <Sparkles className="size-3" />
                      ) : (
                        <Regex className="size-3" />
                      )}
                      {option === 'describe' ? 'Describe' : 'Regex'}
                    </button>
                  ))}
                </div>
              )}

              {kind === 'replace' && (
                <label className="flex min-w-36 flex-1 items-center gap-2 text-[12px] text-dim sm:max-w-64">
                  <span className="shrink-0">Replace with</span>
                  <input
                    value={replacement}
                    onChange={(event) => setReplacement(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && !event.nativeEvent.isComposing) handleSubmit()
                    }}
                    placeholder={mode === 'describe' ? 'from your sentence' : 'nothing'}
                    spellCheck={false}
                    className="h-7 w-full min-w-0 rounded-full bg-muted px-3 font-mono text-[12px] text-foreground inset-ring inset-ring-input outline-none placeholder:text-dim focus:inset-ring-primary/30"
                  />
                </label>
              )}

              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canSubmit}
                aria-label="Run"
                className="ml-auto flex size-9 items-center justify-center rounded-[11px] bg-primary text-primary-foreground transition-opacity disabled:opacity-25"
              >
                <ArrowUp className="size-4" />
              </button>
            </div>
          </div>

          {error ? (
            <Alert variant="destructive">
              <CircleAlert />
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          ) : (
            <p className="px-1 text-[12px] text-dim">{hint()}</p>
          )}
        </div>

        {/* What this can do. Also the transformation picker. */}
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          {KINDS.map(({ kind: option, icon: Icon, title, caption, needsModel }) => {
            const disabled = needsModel && !describeAvailable
            return (
              <button
                key={option}
                type="button"
                disabled={disabled}
                aria-pressed={kind === option}
                onClick={() => chooseKind(option)}
                title={
                  disabled ? 'This server was started without an ANTHROPIC_API_KEY.' : undefined
                }
                className={cn(
                  'flex flex-col gap-2.5 rounded-[12px] bg-card p-3.5 text-left transition-colors inset-ring inset-ring-border disabled:opacity-40',
                  kind === option ? 'inset-ring-primary/25' : 'hover:bg-muted',
                )}
              >
                <span
                  className={cn(
                    'flex size-7 items-center justify-center rounded-[8px]',
                    kind === option ? 'tint text-primary' : 'bg-accent text-dim',
                  )}
                >
                  <Icon className="size-3.5" />
                </span>
                <span className="flex flex-col gap-1">
                  <span className="text-[14px] font-medium">{title}</span>
                  <span className="text-[12px] leading-snug text-dim">{caption}</span>
                </span>
              </button>
            )
          })}
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
          kind === 'replace' && (
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS[mode].map((suggestion) => (
                <button
                  key={suggestion.label}
                  type="button"
                  onClick={() => {
                    setText(suggestion.text)
                    setReplacement(suggestion.replacement)
                  }}
                  className="rounded-full bg-card px-3 py-1.5 text-[12px] text-dim transition-colors inset-ring inset-ring-border hover:text-foreground"
                >
                  {suggestion.label}
                </button>
              ))}
            </div>
          )
        )}

        {recent.length > 0 && !file && (
          <section className="flex flex-col gap-2">
            <h2 className="eyebrow text-dim">Pick up where you left off</h2>
            {recent.map((job) => (
              <Link
                key={job.id}
                href={`/jobs/${job.id}`}
                className="flex items-center gap-3 rounded-[11px] bg-card px-3.5 py-3 transition-colors inset-ring inset-ring-border hover:bg-muted"
              >
                <StatusDot status={job.status} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px]">{fileName(job.file_key)}</span>
                  <span className="block truncate text-[12px] text-dim">
                    {job.prompt ?? job.pattern}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-[11px] text-dim">
                  {since(job.created_at)}
                </span>
                <ChevronRight className="size-3.5 shrink-0 text-dim" />
              </Link>
            ))}
          </section>
        )}
      </div>

      <S3Dialog
        open={dialogOpen}
        onOpenChange={onDialogOpenChange}
        onSelect={(selected) => {
          chooseFile(selected)
          onDialogOpenChange(false)
        }}
      />
    </div>
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
      <Alert variant="destructive">
        <CircleAlert />
        <AlertDescription>Could not read this file. {message}</AlertDescription>
      </Alert>
    )
  }
  if (preview.data?.status !== 'done') {
    return (
      <div className="flex flex-col gap-2" aria-label="Reading the file">
        <p className="eyebrow text-dim">Reading the first rows</p>
        <Skeleton className="h-32 w-full rounded-[12px]" />
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
    <div className="flex flex-col gap-2">
      <h2 className="eyebrow text-dim">The first rows</h2>
      <DataTable
        columns={preview.data.columns}
        rows={preview.data.rows}
        highlighted={columns}
        onToggleColumn={toggle}
      />
      <p className="text-[12px] text-dim">
        {columns.length ? (
          <>
            Applies to <span className="text-foreground">{columns.join(', ')}</span>.{' '}
            <button
              type="button"
              className="underline underline-offset-4 hover:text-foreground"
              onClick={() => onColumnsChange([])}
            >
              Use every column
            </button>
          </>
        ) : kind === 'standardise' ? (
          'Click the header of the column to standardise.'
        ) : kind === 'redact_pii' ? (
          'Looks in every column. Click column headers to look in specific ones only.'
        ) : describing ? (
          'Applies to the columns your sentence names, or to every column. Click headers to choose them yourself.'
        ) : (
          'Applies to every column. Click column headers to choose specific ones.'
        )}
      </p>
    </div>
  )
}
