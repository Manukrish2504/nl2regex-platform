import type { AnchorHTMLAttributes, MouseEvent } from 'react'

import { navigate } from '@/lib/router'

/** A real link (it has an href, so open-in-new-tab works) that navigates without a page load. */
export function Link({ href, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event)
    const plainLeftClick = event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey
    if (event.defaultPrevented || !plainLeftClick) return
    event.preventDefault()
    navigate(href)
  }
  return <a href={href} onClick={handleClick} {...props} />
}
