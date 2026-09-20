/** A failure from the API, carrying its stable error code. Status 0 means the server was not reached. */
export class ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, string[]>

  constructor(status: number, code: string, message: string, fields?: Record<string, string[]>) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}

/** Calls the JSON API. Every failure, whatever its cause, is thrown as an ApiError. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection and try again.')
  }

  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    // The API answers every failure as {"error": {code, message, fields?}}.
    const error = body?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'error',
      error?.message ?? 'Something went wrong.',
      error?.fields,
    )
  }
  return body as T
}
