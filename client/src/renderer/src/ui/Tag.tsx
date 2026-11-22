// Light Table's tag (H22): a short state beside a value, such as a provisional threshold, the comparison that decides,
// an administrator or a disabled account. A state is a tag, never a colour on a whole row.
import type { ReactNode } from 'react'

export function Tag({ tone, children }: { tone?: 'ink' | 'mark' | 'alert'; children: ReactNode }) {
  return <span className="tag" data-tone={tone}>{children}</span>
}
