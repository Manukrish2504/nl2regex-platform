export { cn } from "cn"

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${parseFloat((bytes / 1024 ** index).toFixed(1))} ${units[index]}`
}

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
