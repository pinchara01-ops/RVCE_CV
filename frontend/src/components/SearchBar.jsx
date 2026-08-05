import { useState } from 'react'
import { IconSearch } from '@tabler/icons-react'
import './SearchBar.css'

export default function SearchBar({ defaultValue = '', onSearch, autoFocus = false }) {
  const [value, setValue] = useState(defaultValue)

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    onSearch(trimmed)
  }

  return (
    <form className="search-bar" onSubmit={handleSubmit}>
      <input
        type="text"
        className="search-bar__input"
        placeholder="Search the footage — “someone drops a bag near the entrance”"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoFocus={autoFocus}
      />
      <button type="submit" className="search-bar__button">
        <IconSearch size={15} stroke={2} />
        <span>Search</span>
      </button>
    </form>
  )
}
