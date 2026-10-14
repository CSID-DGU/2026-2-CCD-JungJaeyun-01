import type { Route } from './types'

/** 참여자별 상세 경로의 화면 상태. 이름을 누를 때 불러온다. */
export type RouteEntry =
  | { status: 'loading' }
  | { status: 'ok'; route: Route; note: string | null }
  | { status: 'error'; message: string }

/** (도착 지역, 참여자 순번)별 경로 상태를 담는 키 */
export const routeKey = (stationId: string, participantIndex: number) => `${stationId}:${participantIndex}`

export type RouteEntries = Record<string, RouteEntry>
