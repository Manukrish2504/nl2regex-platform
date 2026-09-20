import { useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, LoaderCircle, Lock } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import { connect, connectionKey } from './api'

// The API's own messages are already specific (wrong keys, no such bucket, no permission,
// S3 unreachable). These two read better rewritten for this screen.
const MESSAGE_OVERRIDES: Record<string, string> = {
  throttled: 'Too many attempts. Wait a minute, then try again.',
  validation_error: 'Check the highlighted fields.',
}

const FIELDS = [
  { name: 'access_key_id', label: 'Access key ID', type: 'text', placeholder: 'AKIA…' },
  { name: 'secret_access_key', label: 'Secret access key', type: 'password', placeholder: '' },
  { name: 'bucket', label: 'Bucket name', type: 'text', placeholder: 'my-data-bucket' },
] as const

export function ConnectForm({ notice }: { notice?: string }) {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  // An uncontrolled form, read once on submit: the secret key never enters React state.
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setPending(true)
    setError(null)
    try {
      const connection = await connect({
        access_key_id: String(values.get('access_key_id')).trim(),
        secret_access_key: String(values.get('secret_access_key')).trim(),
        bucket: String(values.get('bucket')).trim(),
      })
      form.reset()
      queryClient.setQueryData(connectionKey, connection)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'error', 'Something went wrong.'))
    } finally {
      setPending(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" autoComplete="off">
      {notice && !error && (
        <Alert>
          <CircleAlert />
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertDescription>{MESSAGE_OVERRIDES[error.code] ?? error.message}</AlertDescription>
        </Alert>
      )}

      {FIELDS.map((field, index) => {
        const fieldErrors = error?.fields?.[field.name]
        return (
          <div key={field.name} className="flex flex-col gap-1.5">
            <Label htmlFor={field.name}>{field.label}</Label>
            <Input
              id={field.name}
              name={field.name}
              type={field.type}
              placeholder={field.placeholder}
              required
              autoFocus={index === 0}
              autoComplete="off"
              spellCheck={false}
              disabled={pending}
              aria-invalid={fieldErrors ? true : undefined}
              aria-describedby={fieldErrors ? `${field.name}-error` : undefined}
            />
            {fieldErrors && (
              <p id={`${field.name}-error`} className="text-xs text-destructive">
                {fieldErrors.join(' ')}
              </p>
            )}
          </div>
        )
      })}

      <Button type="submit" size="lg" disabled={pending}>
        {pending && <LoaderCircle className="animate-spin" />}
        {pending ? 'Connecting…' : 'Connect'}
      </Button>

      <p className="flex items-start gap-2 text-xs text-muted-foreground">
        <Lock className="mt-0.5 size-3.5 shrink-0" />
        Your keys are encrypted, never shown again, and forgotten after an hour without use.
        Read-only access (s3:ListBucket and s3:GetObject) is all the app needs.
      </p>
    </form>
  )
}
