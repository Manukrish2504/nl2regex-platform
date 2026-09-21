import { useEffect, useState } from 'react'

export type Theme = 'system' | 'dark' | 'light'

const KEY = 'nl2regex-theme'
const DARK = '(prefers-color-scheme: dark)'

function apply(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia(DARK).matches)
  document.documentElement.classList.toggle('dark', dark)
}

/** The chosen appearance, remembered in this browser. "system" follows the operating system. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem(KEY) as Theme | null) ?? 'system',
  )

  useEffect(() => {
    apply(theme)
    localStorage.setItem(KEY, theme)
    if (theme !== 'system') return
    // Only while following the system does its setting need watching.
    const media = window.matchMedia(DARK)
    const onChange = () => apply('system')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [theme])

  return [theme, setTheme] as const
}

/** Set the class before React renders, so the first paint is never the wrong colour. */
export function applyStoredTheme() {
  apply((localStorage.getItem(KEY) as Theme | null) ?? 'system')
}
