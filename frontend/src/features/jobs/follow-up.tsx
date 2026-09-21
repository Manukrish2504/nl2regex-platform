import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowUp, CircleAlert, Combine, EyeOff, Regex, Replace, Sparkles } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { useConfig } from '@/features/config/api'
import { ApiError } from '@/lib/api'
import { navigate } from '@/lib/router'
import { cn } from '@/lib/utils'
import { submitJob, type Job, type JobKind, type JobRequest } from './api'

type Mode = 'describe' | 'regex'

const KINDS: { kind: JobKind; icon: typeof Replace; label: string }[] = [
  { kind: 'replace', icon: Replace, label: 'Find and replace' },
  { kind: 'redact_pii', icon: EyeOff, label: 'Redact personal data' },
  { kind: 'standardise', icon: Combine, label: 'Standardise a column' },
]

/**
 * Ask for one more change, to what this job produced. The new job reads the earlier job's
 * output instead of the file in the bucket, so the two are a conversation about one file and
 * the original is still untouched.
 */
export function FollowUp({ job }: { job: Job }) {
  const queryClient = useQueryClient()
  const { data: config } = useConfig()
  const [kind, setKind] = useState<JobKind>('replace')
  const [mode, setMode] = useState<Mode>('describe')
  const [text, setText] = useState('')
  const [replacement, setReplacement] = useState('')
  const [column, setColumn] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const describeAvailable = config?.describe_available ?? false
  const ready =
    kind === 'replace' ? text.trim() !== '' : kind === 'standardise' ? column.trim() !== '' : true
  const canSubmit = ready && !submitting

  async function handleSubmit() {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const target = { source_job_id: job.id, columns: kind === 'standardise' ? [column.trim()] : [] }
      const request: JobRequest =
        kind === 'redact_pii'
          ? { ...target, kind }
          : kind === 'standardise'
            ? { ...target, kind, ...(text.trim() ? { prompt: text.trim() } : {}) }
            : mode === 'describe'
              ? { ...target, replacement, prompt: text }
              : { ...target, replacement, pattern: text }
      const next = await submitJob(request)
      queryClient.setQueryData(['jobs', next.id], next)
      queryClient.invalidateQueries({ queryKey: ['jobs'], exact: true })
      navigate(`/jobs/${next.id}`)
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught : new ApiError(0, 'error', 'Something went wrong.'),
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-2.5 rounded-[14px] bg-popover p-3 shadow-[inset_0_0_0_1px_var(--surface-edge)]">
        {kind === 'redact_pii' ? (
          <p className="px-1 py-1.5 text-[14px] text-muted-foreground">
            Look through this result for personal data and mask what is found.
          </p>
        ) : (
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
              event.preventDefault()
              handleSubmit()
            }}
            rows={1}
            placeholder={
              kind === 'standardise'
                ? 'Optional: how should the values be written?'
                : mode === 'describe'
                  ? 'Ask for one more change to this result…'
                  : 'Another regular expression…'
            }
            aria-label="Ask for one more change"
            className={cn(
              'field-sizing-content max-h-[30vh] w-full resize-none bg-transparent px-1 py-1.5 text-[14px] outline-none placeholder:text-dim',
              kind === 'replace' && mode === 'regex' && 'font-mono text-[13px]',
            )}
          />
        )}

        <div className="flex flex-wrap items-center gap-1.5">
          <div className="flex rounded-full bg-muted p-0.5 inset-ring inset-ring-input" role="group" aria-label="Transformation">
            {KINDS.map(({ kind: option, icon: Icon, label }) => (
              <button
                key={option}
                type="button"
                aria-pressed={kind === option}
                aria-label={label}
                title={
                  option !== 'replace' && !describeAvailable
                    ? 'This server was started without an ANTHROPIC_API_KEY.'
                    : label
                }
                disabled={option !== 'replace' && !describeAvailable}
                onClick={() => setKind(option)}
                className={cn(
                  'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] transition-colors disabled:opacity-40',
                  kind === option ? 'tint text-primary' : 'text-dim hover:text-foreground',
                )}
              >
                <Icon className="size-3" />
                <span className={cn(kind !== option && 'sr-only')}>{label}</span>
              </button>
            ))}
          </div>

          {kind === 'replace' && describeAvailable && (
            <button
              type="button"
              onClick={() => setMode(mode === 'describe' ? 'regex' : 'describe')}
              className="flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[12px] text-dim transition-colors inset-ring inset-ring-input hover:text-foreground"
            >
              {mode === 'describe' ? <Sparkles className="size-3" /> : <Regex className="size-3" />}
              {mode === 'describe' ? 'Describe' : 'Regex'}
            </button>
          )}

          {kind === 'replace' && (
            <input
              value={replacement}
              onChange={(event) => setReplacement(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) handleSubmit()
              }}
              placeholder="Replace with…"
              aria-label="Replace with"
              spellCheck={false}
              className="h-7 w-36 rounded-full bg-muted px-3 font-mono text-[12px] inset-ring inset-ring-input outline-none placeholder:text-dim focus:inset-ring-primary/30"
            />
          )}

          {kind === 'standardise' && (
            <input
              value={column}
              onChange={(event) => setColumn(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) handleSubmit()
              }}
              placeholder="Which column?"
              aria-label="Which column to standardise"
              className="h-7 w-40 rounded-full bg-muted px-3 text-[12px] inset-ring inset-ring-input outline-none placeholder:text-dim focus:inset-ring-primary/30"
            />
          )}

          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            aria-label="Run the follow-up"
            className="ml-auto flex size-8 items-center justify-center rounded-[10px] bg-primary text-primary-foreground transition-opacity disabled:opacity-25"
          >
            <ArrowUp className="size-3.5" />
          </button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}
    </div>
  )
}
