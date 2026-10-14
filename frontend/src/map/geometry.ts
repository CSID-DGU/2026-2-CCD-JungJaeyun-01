// 지도에 그릴 경로 도형을 만드는 순수 함수들 (카카오 SDK에 의존하지 않는다).
import type { LatLng, Route, RouteMode } from '../types'

export interface DrawLeg {
  mode: RouteMode
  dashed: boolean
  color: string
  weight: number
  path: LatLng[]
}

export interface DrawableRoute {
  color: string
  legs: DrawLeg[]
  /** 환승 지점 (두 번째 이후 대중교통 구간이 시작되는 곳) */
  transfers: LatLng[]
  /** 버스를 타는 지점 (버스 아이콘 표시용). legIndex는 legs 안의 위치 */
  busBoardings: { legIndex: number; point: LatLng; color: string }[]
  /** 추정 경로일 때의 표시 문구 */
  estimatedLabel: string | null
}

const EARTH_RADIUS_M = 6371000

export function distanceM(a: LatLng, b: LatLng): number {
  const toRad = Math.PI / 180
  const dLat = (b.lat - a.lat) * toRad
  const dLng = (b.lng - a.lng) * toRad * Math.cos(((a.lat + b.lat) / 2) * toRad)
  return Math.hypot(dLat, dLng) * EARTH_RADIUS_M
}

export function pathLengthM(path: LatLng[]): number {
  let total = 0
  for (let i = 1; i < path.length; i++) total += distanceM(path[i - 1], path[i])
  return total
}

/** 경로의 처음부터 d미터 지점까지의 좌표열 (마지막 점은 보간). 항상 2점 이상을 돌려준다. */
export function partialPath(path: LatLng[], d: number): LatLng[] {
  const out: LatLng[] = [path[0]]
  let walked = 0
  for (let i = 1; i < path.length; i++) {
    const seg = distanceM(path[i - 1], path[i])
    if (walked + seg >= d) {
      const t = seg === 0 ? 1 : Math.max(0, (d - walked) / seg)
      out.push({
        lat: path[i - 1].lat + (path[i].lat - path[i - 1].lat) * t,
        lng: path[i - 1].lng + (path[i].lng - path[i - 1].lng) * t,
      })
      return out
    }
    out.push(path[i])
    walked += seg
  }
  return out.length >= 2 ? out : [path[0], path[0]]
}

/**
 * 공통 경로 스키마(route)를 지도용 도형으로 바꾼다.
 * 지하철·버스는 노선 색 실선(색이 없으면 참여자 색), 도보는 점선.
 * 추정 경로(source='estimate')는 모든 구간을 점선으로 그리고 "추정 경로"라고 표시한다.
 */
export function buildDrawable(route: Route, color: string): DrawableRoute {
  const estimated = route.source === 'estimate'
  const legs: DrawLeg[] = route.segments.map((seg) => ({
    mode: seg.mode,
    dashed: seg.mode === 'WALK' || estimated,
    color: seg.mode === 'WALK' ? color : (seg.lineColor ?? color),
    weight: seg.mode === 'WALK' ? 4 : 6,
    path: seg.path.map(([lat, lng]) => ({ lat, lng })),
  }))
  const transfers: LatLng[] = []
  let seenTransit = false
  route.segments.forEach((seg, i) => {
    if (seg.mode === 'WALK') return
    if (seenTransit) transfers.push(legs[i].path[0])
    seenTransit = true
  })
  const busBoardings = legs.flatMap((leg, legIndex) =>
    leg.mode === 'BUS' ? [{ legIndex, point: leg.path[0], color: leg.color }] : [],
  )
  return { color, legs, transfers, busBoardings, estimatedLabel: estimated ? '추정 경로' : null }
}

/** 지도 범위를 맞출 때 쓰는, 경로가 지나는 모든 좌표 */
export function routePoints(route: DrawableRoute): LatLng[] {
  return route.legs.flatMap((leg) => leg.path)
}
