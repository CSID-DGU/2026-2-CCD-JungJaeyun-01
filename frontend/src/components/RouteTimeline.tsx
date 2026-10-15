import { useEffect, useState, type CSSProperties } from 'react'
import { legColor } from '../map/geometry'
import { fitMinutes, lineLabel } from '../routeFormat'
import { fmtClock, fmtDay, minutesBetween } from '../meeting'
import type { Route, RouteSegment } from '../types'
import { formatArrival, realtimeQuery, REFRESH_MS, useArrivals } from '../useArrivals'

export interface TimelinePlay {
  /** 바뀔 때마다 등장 모션을 처음부터 다시 재생한다 */
  token: number
  /** 이 참여자의 지도 경로 그리기가 시작되는 시차 (모두 보기에서 참여자마다 0.2초씩) */
  delayMs: number
}

interface Props {
  route: Route
  /** 참여자 색 (도보 구간 색) */
  color: string
  originName: string
  originAddress: string
  destinationName: string
  /** 약속 시간 (KST ISO 8601) */
  meetingTime: string
  focusedSegment: number | null
  onFocusSegment: (segment: number | null) => void
  /** null이면 아직 지도에서 경로 그리기가 시작되기 전이라 숨겨 둔다 */
  play: TimelinePlay | null
  /** "실시간 도착정보 활성화"로 직접 켠 실시간 모드 */
  liveManual: boolean
}

/** 출발 시각 30분 전부터 자동으로 실시간 모드 */
const AUTO_LIVE_BEFORE_MS = 30 * 60_000

const TOTAL_ANIMATION_MS = 1000

const fmtDistance = (m: number) => (m < 1000 ? `${Math.round(m)}m` : `${(m / 1000).toFixed(1)}km`)

/** 노선 배지: 지하철은 노선 색 배지, 버스는 버스 번호 배지 (Google이 준 색·글자색 그대로) */
export function LineBadge({ seg, fallbackColor }: { seg: RouteSegment; fallbackColor: string }) {
  return (
    <span className={`line-badge ${seg.mode.toLowerCase()}`} style={{ background: legColor(seg, fallbackColor), color: seg.lineTextColor ?? '#fff' }}>
      {seg.mode === 'BUS' && <span aria-hidden="true">🚌 </span>}
      {lineLabel(seg)}
    </span>
  )
}

type Row =
  | { kind: 'node'; id: string; time: string | null; title: string; sub?: string; color: string; end?: boolean; seg?: RouteSegment; transfer?: boolean; live?: boolean }
  | { kind: 'leg'; id: string; index: number; seg: RouteSegment }

function buildRows(route: Route, color: string, originName: string, originAddress: string, destinationName: string): Row[] {
  const segs = route.segments
  const rows: Row[] = [
    { kind: 'node', id: 'start', time: route.departureTime, title: '출발지', sub: originAddress || originName, color: legColor(segs[0], color) },
  ]
  segs.forEach((seg, i) => {
    const prev = segs[i - 1]
    const next = segs[i + 1]
    if (seg.mode !== 'WALK') {
      if (i === 0) {
        // 도보 없이 바로 타는 경우: 출발지가 곧 승차역이다.
        const start = rows[0] as Extract<Row, { kind: 'node' }>
        start.sub = `${originAddress || originName} · ${seg.from ?? ''} 승차`
        start.seg = seg
        start.live = true
      } else {
        rows.push({
          kind: 'node', id: `board-${i}`, time: seg.departureTime, title: seg.from ?? '승차역',
          sub: prev.mode === 'WALK' ? '승차' : '환승', color: legColor(seg, color), seg, transfer: prev.mode !== 'WALK',
          live: !segs.slice(0, i).some((s) => s.mode !== 'WALK'), // 첫 번째 승차만 지금의 실시간이 의미 있다
        })
      }
    }
    rows.push({ kind: 'leg', id: `leg-${i}`, index: i, seg })
    if (seg.mode !== 'WALK' && next && next.mode === 'WALK') {
      rows.push({ kind: 'node', id: `alight-${i}`, time: seg.arrivalTime, title: seg.to ?? '하차역', sub: '하차', color: legColor(seg, color) })
    }
  })
  const last = segs[segs.length - 1]
  rows.push({
    kind: 'node', id: 'end', time: route.arrivalTime, title: destinationName,
    sub: last.mode !== 'WALK' ? `하차 · ${last.to ?? ''}` : '도착', color: legColor(last, color), end: true,
  })
  return rows
}

function StopsDetail({ seg }: { seg: RouteSegment }) {
  if (seg.intermediateStops && seg.intermediateStops.length > 0) {
    return (
      <div className="tl-stops">
        <ol>
          {seg.intermediateStops.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ol>
      </div>
    )
  }
  if (seg.intermediateStops && seg.intermediateStops.length === 0) {
    return <div className="tl-stops"><small>경유 정거장 없이 바로 다음 정거장이에요.</small></div>
  }
  return (
    <div className="tl-stops">
      <small>
        {seg.mode === 'BUS'
          ? 'Google이 경유 정류장 이름을 제공하지 않아요.'
          : '노선도의 정거장 수와 달라서(급행·지선 등) 틀린 목록을 보여주지 않으려고 표시하지 않아요.'}
      </small>
    </div>
  )
}

/** 승차역 옆의 "3분 후 도착 · 2정거장 전" (첫 번째·두 번째 열차/버스) */
function LiveArrivals({ seg, active }: { seg: RouteSegment; active: boolean }) {
  const state = useArrivals(realtimeQuery(seg), active)
  if (!active) return null
  if (state.loading) return <span className="tl-live loading">실시간 불러오는 중…</span>
  if (state.unavailable || state.items.length === 0) return <span className="tl-live none">실시간 정보 없음</span>
  return (
    <span className="tl-live" aria-live="polite">
      {state.items.map((a, i) => (
        <span key={i} className="tl-live-row"><b>{i === 0 ? '첫 번째' : '두 번째'}</b> {formatArrival(a)}</span>
      ))}
      {state.updatedAt && <small>{fmtClock(new Date(state.updatedAt).toISOString())} 갱신 · {REFRESH_MS / 1000}초마다 자동</small>}
    </span>
  )
}

export default function RouteTimeline(props: Props) {
  const { route, color, originName, originAddress, destinationName, meetingTime, focusedSegment, onFocusSegment, play, liveManual } = props
  // 출발 시각 30분 전이 되면 자동으로 실시간 모드로 바뀐다 (30초마다 시각을 다시 확인)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), REFRESH_MS)
    return () => clearInterval(t)
  }, [])
  const autoLive = route.departureTime !== null && now >= new Date(route.departureTime).getTime() - AUTO_LIVE_BEFORE_MS
  const live = liveManual || autoLive
  const [openStops, setOpenStops] = useState<Set<number>>(new Set())
  const rows = buildRows(route, color, originName, originAddress, destinationName)
  const step = TOTAL_ANIMATION_MS / rows.length

  const departure = route.departureTime
  const arrival = route.arrivalTime
  const total = route.totalMinutes // 소요시간은 경로 상세의 이 값 하나만 쓴다
  const fitted = fitMinutes(route)
  const early = arrival ? minutesBetween(arrival, meetingTime) : null
  const walkMinutes = route.walkMinutes ?? 0

  const delay = (i: number): CSSProperties => ({ ['--d' as string]: `${(play?.delayMs ?? 0) + i * step}ms`, ['--step' as string]: `${step}ms` })

  return (
    <div className="timeline-wrap">
      <header className="tl-summary">
        <p className="tl-headline">
          <strong>{fmtClock(departure)} 출발</strong>
          <span className="tl-arrow" aria-hidden="true">→</span>
          <strong>{fmtClock(arrival)} 도착</strong>
          <span className="tl-total">({total}분)</span>
        </p>
        <p className="tl-meeting">
          약속 {fmtDay(meetingTime)} {fmtClock(meetingTime)} 도착 기준
          {early !== null && (early > 0 ? ` · ${early}분 일찍 도착` : early === 0 ? ' · 정시 도착' : ` · ${-early}분 늦음`)}
        </p>
        <ol className="tl-flow" aria-label="이동 수단 흐름">
          {route.segments.map((seg, i) => (
            <li key={i}>
              {seg.mode === 'WALK' ? (
                <span className="flow-walk" title={`도보 ${fitted[i]}분`}>
                  <span aria-hidden="true">🚶</span>
                  <small>{fitted[i]}분</small>
                </span>
              ) : (
                <LineBadge seg={seg} fallbackColor={color} />
              )}
            </li>
          ))}
        </ol>
        <p className="tl-meta">
          환승 {route.transfers}회 · 총 도보 {Math.round(walkMinutes)}분{route.walkMeters ? ` (${fmtDistance(route.walkMeters)})` : ''}
        </p>
      </header>

      <ol className={`tl${play ? ' play' : ''}`} key={play?.token ?? 0} aria-label="상세 경로 타임라인">
        {rows.map((row, i) => {
          if (row.kind === 'node') {
            return (
              <li key={row.id} className={`tl-item tl-node${row.end ? ' end' : ''}`} style={delay(i)}>
                <span className="tl-time">{fmtClock(row.time)}</span>
                <span className="tl-rail"><i className="tl-dot" style={{ borderColor: row.color }} /></span>
                <div className="tl-body">
                  <strong>{row.title}{row.transfer && <em className="tl-transfer">환승</em>}</strong>
                  {row.seg && (
                    <span className="tl-board">
                      <LineBadge seg={row.seg} fallbackColor={color} />
                      {row.seg.headsign && <span className="tl-headsign">{row.seg.headsign}</span>}
                    </span>
                  )}
                  {row.sub && !row.transfer && <small>{row.sub}</small>}
                  {row.live && row.seg && <LiveArrivals seg={row.seg} active={live} />}
                </div>
              </li>
            )
          }
          const { seg, index } = row
          const focused = focusedSegment === index
          const color_ = legColor(seg, color)
          const walk = seg.mode === 'WALK'
          const stopsOpen = openStops.has(index)
          return (
            <li
              key={row.id}
              className={`tl-item tl-leg ${walk ? 'walk' : 'transit'}${focused ? ' selected' : ''}${focusedSegment !== null && !focused ? ' dim' : ''}`}
              style={{ ...delay(i), ['--leg' as string]: color_ }}
            >
              <span className="tl-time" />
              <span className="tl-rail"><i className="tl-line" /></span>
              <div className="tl-body">
                <button
                  type="button"
                  className="tl-leg-btn"
                  aria-pressed={focused}
                  title="지도에서 이 구간만 강조하고 이동"
                  onClick={() => onFocusSegment(focused ? null : index)}
                >
                  {walk ? (
                    <span className="tl-walk">
                      <span aria-hidden="true">🚶</span> 도보 약 {fitted[index]}분
                      {seg.distanceMeters ? ` · ${fmtDistance(seg.distanceMeters)}` : ''}
                    </span>
                  ) : (
                    <>
                      <span className="tl-transit-head">
                        <LineBadge seg={seg} fallbackColor={color} />
                        {seg.headsign && <span className="tl-headsign">{seg.headsign}</span>}
                      </span>
                      <span className="tl-transit-meta">
                        {fitted[index]}분{seg.stopCount ? ` · ${seg.stopCount}개 ${seg.mode === 'BUS' ? '정류장' : '정거장'}` : ''}
                      </span>
                    </>
                  )}
                </button>
                {seg.mode === 'SUBWAY' && (
                  <>
                    <button
                      type="button"
                      className="tl-toggle"
                      aria-expanded={stopsOpen}
                      onClick={() =>
                        setOpenStops((cur) => {
                          const next = new Set(cur)
                          if (next.has(index)) next.delete(index)
                          else next.add(index)
                          return next
                        })
                      }
                    >
                      경유 정거장 {Math.max((seg.stopCount ?? 1) - 1, seg.intermediateStops?.length ?? 0)}개 {stopsOpen ? '접기 ▴' : '보기 ▾'}
                    </button>
                    <div className={`tl-collapse${stopsOpen ? ' open' : ''}`} aria-hidden={!stopsOpen}>
                      <div className="tl-collapse-inner">
                        <StopsDetail seg={seg} />
                      </div>
                    </div>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
