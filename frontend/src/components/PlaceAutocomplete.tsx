import { useEffect, useState } from 'react'
import { searchPlaces } from '../api'
import type { PlaceHit } from '../types'

interface Props {
  id: string
  value: PlaceHit | null
  onChange: (hit: PlaceHit | null) => void
  hasError?: boolean
}

const DEBOUNCE_MS = 300

/** 출발지 검색 입력. 입력이 멈춘 뒤 300ms 후에 백엔드 검색 프록시를 호출한다. */
export default function PlaceAutocomplete({ id, value, onChange, hasError }: Props) {
  const [text, setText] = useState(value?.name ?? '')
  const [results, setResults] = useState<PlaceHit[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState(-1)

  // 선택된 값이 있으면 그 이름을 보여주고, 검색 결과·로딩 표시는 입력 중일 때만 쓴다 (렌더 중에 계산).
  const query = text.trim()
  const searching = !value && query !== ''
  const shown = searching ? results : []
  const inputText = value ? value.name : text

  useEffect(() => {
    if (!searching) return
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const hits = await searchPlaces(query, controller.signal)
        setResults(hits)
        setActive(-1)
        setOpen(true)
      } catch (e) {
        if (controller.signal.aborted) return
        setResults([])
        setError(e instanceof Error ? e.message : '검색에 실패했습니다.')
        setOpen(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [searching, query])

  function select(hit: PlaceHit) {
    onChange(hit)
    setOpen(false)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') setOpen(false)
    else if (e.key === 'ArrowDown' && shown.length) {
      e.preventDefault()
      setActive((i) => (i + 1) % shown.length)
    } else if (e.key === 'ArrowUp' && shown.length) {
      e.preventDefault()
      setActive((i) => (i <= 0 ? shown.length - 1 : i - 1))
    } else if (e.key === 'Enter' && open && active >= 0) {
      e.preventDefault()
      select(shown[active])
    }
  }

  const showEmpty = searching && open && !loading && !error && shown.length === 0

  return (
    <div className="autocomplete">
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        autoComplete="off"
        placeholder="출발지 검색 (예: 홍대입구역, 강남구청)"
        value={inputText}
        className={hasError ? 'invalid' : value ? 'selected' : ''}
        onChange={(e) => {
          setText(e.target.value)
          if (value) onChange(null)
        }}
        onFocus={() => shown.length > 0 && setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {searching && loading && <span className="spinner small" aria-label="검색 중" />}
      {open && searching && (shown.length > 0 || error || showEmpty) && (
        <ul className="suggestions" id={`${id}-list`} role="listbox">
          {error && <li className="suggestion-note error">{error}</li>}
          {showEmpty && <li className="suggestion-note">검색 결과가 없습니다.</li>}
          {shown.map((hit, i) => (
            <li
              key={hit.id}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              // blur보다 먼저 선택되도록 mousedown을 쓴다.
              onMouseDown={(e) => {
                e.preventDefault()
                select(hit)
              }}
            >
              <strong>{hit.name}</strong>
              <span>{hit.address}</span>
            </li>
          ))}
        </ul>
      )}
      {value && <p className="origin-address">{value.address}</p>}
    </div>
  )
}
