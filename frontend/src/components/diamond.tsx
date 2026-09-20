import { cn } from '@/lib/utils'

/** The mark that runs through the design: a small rotated square, filled when something is live. */
export function Diamond({ className, filled = true }: { className?: string; filled?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block size-[7px] shrink-0 rotate-45 rounded-[1px]',
        filled ? 'bg-current' : 'ring-1 ring-current ring-inset',
        className,
      )}
    />
  )
}
