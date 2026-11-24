// H61: one filter of the attempt history as a pill. Closed it names the filter; set, it shows its value and can be
// removed on its own; opened, it lists the choices for the pointer and the keys alike (arrows, Home, End, Enter or
// Space to choose, Escape to close).
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Icon } from '../ui/Icon'

export interface Choice<V extends string> {
  value: V
  label: ReactNode
}

export function FilterPill<V extends string>({ name, choices, value, shown, onChange, removeLabel }: {
  name: string
  choices: ReadonlyArray<Choice<V>>
  value: V | null
  shown: ReactNode // what a set pill shows
  onChange(value: V | null): void
  removeLabel: string
}) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const options = list.current?.querySelectorAll<HTMLElement>('[role="option"]')
    const chosen = list.current?.querySelector<HTMLElement>('[aria-selected="true"]')
    ;(chosen ?? options?.[0])?.focus()
    const away = (event: PointerEvent) => {
      const target = event.target as Node
      if (!list.current?.contains(target) && !button.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])

  function close() {
    setOpen(false)
    button.current?.focus()
  }

  function choose(next: V) {
    onChange(next)
    close()
  }

  function keys(event: KeyboardEvent<HTMLUListElement>) {
    const options = [...(list.current?.querySelectorAll<HTMLElement>('[role="option"]') ?? [])]
    const at = options.indexOf(document.activeElement as HTMLElement)
    const move = (to: number) => {
      event.preventDefault()
      options[(to + options.length) % options.length]?.focus()
    }
    if (event.key === 'ArrowDown') move(at + 1)
    else if (event.key === 'ArrowUp') move(at - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(options.length - 1)
    else if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'Tab') setOpen(false)
  }

  return (
    <span className="filter" data-on={value !== null ? '' : undefined}>
      <button
        ref={button}
        type="button"
        className="filter__open"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
      >
        <span>{value !== null ? shown : name}</span>
        {value === null && <Icon name="chevron" />}
      </button>
      {value !== null && (
        <button type="button" className="filter__remove" aria-label={`${removeLabel}: ${name}`} onClick={() => onChange(null)}>
          <Icon name="close" />
        </button>
      )}
      {open && (
        <ul ref={list} id={id} role="listbox" aria-label={name} className="filter__menu" onKeyDown={keys}>
          {choices.map((choice) => (
            <li
              key={choice.value}
              role="option"
              aria-selected={choice.value === value}
              tabIndex={-1}
              onClick={() => choose(choice.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  choose(choice.value)
                }
              }}
            >
              {choice.label}
            </li>
          ))}
        </ul>
      )}
    </span>
  )
}
