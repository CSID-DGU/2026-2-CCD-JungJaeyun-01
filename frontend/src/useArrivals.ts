import { useEffect, useRef, useState } from 'react'
import { fetchRealtime, type Arrival, type RealtimeQuery } from './api'
import type { RouteSegment } from './types'

export const REFRESH_MS = 30_000

/** 승차 구간에서 실시간 조회에 쓸 값을 뽑는다. 못 만들면 null (그 구간은 실시간 표시를 하지 않는다). */
export function realtimeQuery(seg: RouteSegment): RealtimeQuery | null {
  if (!seg.lineName) return null
  const board = seg.realtime?.boardStop
  const name = board?.name ?? seg.from
  if (!name) return null
  if (seg.mode === 'SUBWAY') {
    const next = seg.intermediateStops?.[0] ?? (seg.stopCount === 1 ? seg.to : null)
    return { type: 'subway', station: name, line: seg.lineName, headsign: seg.headsign, next }
  }
  if (seg.mode === 'BUS' && board?.lat != null && board.lng != null) {
    return { type: 'bus', stop: name, line: seg.lineName, lat: board.lat, lng: board.lng }
  }
  return null
}

export interface ArrivalsState {
  /** 아직 첫 응답 전 */
  loading: boolean
  items: Arrival[]
  /** 실시간 정보를 못 구했다 (키 없음·서울 밖·실패 모두 같은 표시) */
  unavailable: boolean
  updatedAt: number | null
}

const IDLE: ArrivalsState = { loading: false, items: [], unavailable: false, updatedAt: null }

/**
 * active인 동안 30초마다 도착 정보를 갱신한다. active가 꺼지거나 컴포넌트가 사라지면(화면을 떠나면) 즉시 멈추고,
 * 탭이 숨겨져 있는 동안은 요청하지 않는다.
 */
export function useArrivals(query: RealtimeQuery | null, active: boolean): ArrivalsState {
  const [state, setState] = useState<ArrivalsState>(IDLE)
  const key = query ? JSON.stringify(query) : ''
  const queryRef = useRef(query)
  useEffect(() => {
    queryRef.current = query
  })

  useEffect(() => {
    const q = queryRef.current
    if (!active || !q) {
      setState(IDLE)
      return
    }
    let stopped = false
    let controller: AbortController | null = null
    const load = async () => {
      if (document.hidden) return
      controller = new AbortController()
      try {
        const res = await fetchRealtime(q, controller.signal)
        if (!stopped) setState({ loading: false, items: res.items, unavailable: !res.available, updatedAt: res.updatedAt * 1000 })
      } catch {
        if (!stopped) setState((s) => ({ ...s, loading: false, items: [], unavailable: true }))
      }
    }
    setState({ ...IDLE, loading: true })
    void load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      stopped = true
      clearInterval(timer)
      controller?.abort()
    }
  }, [active, key])

  return state
}

/** "3분 후 도착 · 2정거장 전" */
export function formatArrival(a: Arrival): string {
  const time =
    a.seconds === null ? a.text || '도착 예정' : a.seconds < 60 ? '곧 도착' : `${Math.round(a.seconds / 60)}분 후 도착`
  const stops = a.stopsAway === null ? '' : a.stopsAway === 0 ? ' · 도착 중' : ` · ${a.stopsAway}정거장 전`
  return time + stops
}
