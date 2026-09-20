export { cn } from "cn"

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${parseFloat((bytes / 1024 ** index).toFixed(1))} ${units[index]}`
}

/**
 * A value as a language model is shown it: every letter becomes "a" and every digit "9". The
 * server does the same before anything is sent; this copy only shows the user an example.
 */
export const shapeOf = (value: string) =>
  value.replace(/\p{Lu}/gu, "A").replace(/\p{L}/gu, "a").replace(/\p{Nd}/gu, "9")

const loose = (name: string) => name.toLowerCase().replace(/[ _-]/g, "")

/**
 * The columns a job's names refer to, found the way the server finds them: an exact name first,
 * then ignoring case, spaces, underscores and hyphens ("the email column" is `Email`).
 */
export function resolveColumns(wanted: string[], available: string[]): string[] {
  return wanted.flatMap((name) => {
    const found = available.includes(name) ? name : available.find((other) => loose(other) === loose(name))
    return found ? [found] : []
  })
}

/** "samples/archive/old.csv" -> "old.csv" */
export const fileName = (key: string) => key.split("/").pop() ?? key

/** "2h", "3d", "Mon" or a date: how long ago something happened, in as few characters as possible. */
export function since(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return "now"
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  if (seconds < 7 * 86400) return new Date(iso).toLocaleDateString(undefined, { weekday: "short" })
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

/** "15.2s", or "2m 05s" once it runs into minutes. */
export function duration(from: string, to: string): string {
  const seconds = (new Date(to).getTime() - new Date(from).getTime()) / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.floor(seconds / 60)}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`
}

