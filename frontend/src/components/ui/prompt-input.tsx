import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react"
import { ArrowUp } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

interface PromptInputProps {
  value: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  canSubmit: boolean
  placeholder?: string
  /** Chips shown above the text, such as the chosen file. */
  attachments?: ReactNode
  /** Controls on the left of the action bar. */
  actions?: ReactNode
  className?: string
  /** Extra classes for the text itself, such as a monospace font for code. */
  inputClassName?: string
  /** Shown in place of the text area, for a request that takes no text. */
  body?: ReactNode
}

/**
 * The chat-style composer: a text area that grows with its content, an action bar, and a send
 * button. Presentational only; what the actions and attachments are is up to the caller.
 */
function PromptInput({
  value,
  onValueChange,
  onSubmit,
  canSubmit,
  placeholder,
  attachments,
  actions,
  className,
  inputClassName,
  body,
}: PromptInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // The text area is sized to its content, so the box grows with the text. CSS can do this alone
  // (field-sizing: content), but Safari and Firefox do not support that yet, so it is measured.
  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = "auto"
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [value])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends and Shift+Enter breaks the line. While an input method is composing text
    // (Japanese, Chinese, Korean), Enter confirms the composition and must not send.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (canSubmit) onSubmit()
  }

  return (
    <div
      data-slot="prompt-input"
      className={cn(
        "rounded-3xl border border-input bg-card/80 p-3 shadow-xl shadow-black/30 backdrop-blur-md transition-[border-color,box-shadow] focus-within:border-ring/60 focus-within:ring-4 focus-within:ring-ring/15",
        className
      )}
    >
      {attachments && <div className="flex flex-wrap gap-2 px-1 pb-2">{attachments}</div>}

      {/* The text area itself never scrolls (overflow-hidden): a measured height can land a
          fraction of a pixel short at some zoom levels, and that alone would draw a scrollbar.
          This wrapper scrolls instead, and only once the text outgrows the height cap. */}
      <div className="max-h-[45vh] overflow-y-auto">
        {body ?? (
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label={placeholder}
          rows={1}
          className={cn(
            "min-h-12 resize-none overflow-hidden rounded-none border-0 bg-transparent px-2 py-1.5 text-base focus-visible:ring-0 md:text-base dark:bg-transparent",
            inputClassName
          )}
        />
        )}
      </div>

      <div className="flex items-end justify-between gap-2 pt-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{actions}</div>
        <Button
          type="button"
          size="icon"
          className="rounded-full"
          disabled={!canSubmit}
          onClick={onSubmit}
          aria-label="Run"
        >
          <ArrowUp />
        </Button>
      </div>
    </div>
  )
}

export { PromptInput }
