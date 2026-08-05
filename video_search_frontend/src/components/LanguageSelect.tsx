import { Languages } from 'lucide-react'
import { LANGUAGE_OPTIONS } from '../lib/languages'

interface LanguageSelectProps {
  value: string
  onChange: (code: string) => void
  disabled: boolean
}

export function LanguageSelect({ value, onChange, disabled }: LanguageSelectProps) {
  return (
    <div className="liquid-glass flex shrink-0 items-center gap-2 rounded-full py-2 pl-4 pr-3">
      <Languages size={16} className="shrink-0 text-paper-300/50" />
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Query language"
        className="appearance-none bg-transparent pr-1 text-sm text-white outline-none disabled:opacity-50"
      >
        {LANGUAGE_OPTIONS.map((lang) => (
          <option key={lang.code} value={lang.code} className="bg-ink-900 text-white">
            {lang.label}
          </option>
        ))}
      </select>
    </div>
  )
}
