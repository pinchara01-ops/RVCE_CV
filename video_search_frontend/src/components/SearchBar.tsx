import { useEffect, useState } from 'react'
import { ArrowRight } from 'lucide-react'

const EXAMPLE_QUERIES = [
  'a person opening a red door at night',
  'व्यक्ति दरवाज़ा खोलता है',
  'ಒಬ್ಬ ವ್ಯಕ್ತಿ ರಾತ್ರಿ ಕೆಂಪು ಬಾಗಿಲು ತೆರೆಯುತ್ತಿದ್ದಾನೆ',
]

interface SearchBarProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled: boolean
}

export function SearchBar({ value, onChange, onSubmit, disabled }: SearchBarProps) {
  const [placeholderIndex, setPlaceholderIndex] = useState(0)
  const [fade, setFade] = useState(true)

  useEffect(() => {
    const interval = setInterval(() => {
      setFade(false)
      const timeout = setTimeout(() => {
        setPlaceholderIndex((i) => (i + 1) % EXAMPLE_QUERIES.length)
        setFade(true)
      }, 250)
      return () => clearTimeout(timeout)
    }, 3200)
    return () => clearInterval(interval)
  }, [])

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!disabled && value.trim()) onSubmit()
      }}
      className="liquid-glass mx-auto flex w-full max-w-xl items-center gap-3 rounded-full py-2 pl-6 pr-2"
    >
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={EXAMPLE_QUERIES[placeholderIndex]}
        disabled={disabled}
        className={`min-w-0 flex-1 bg-transparent text-base text-white outline-none placeholder:text-white/40 placeholder:transition-opacity placeholder:duration-300 ${
          fade ? 'placeholder:opacity-100' : 'placeholder:opacity-0'
        }`}
        aria-label="Search your footage"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="flex shrink-0 items-center justify-center rounded-full bg-white p-3 text-black transition-opacity disabled:opacity-40"
        aria-label="Run search"
      >
        <ArrowRight size={20} />
      </button>
    </form>
  )
}
