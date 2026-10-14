/** 지도 연출을 일으킨 동작. App이 동작마다 id를 올려 MapView에 알린다. */
export type MotionKind = 'origins' | 'search' | 'region' | 'place' | 'route' | 'view' | 'none'

export interface MotionRequest {
  id: number
  kind: MotionKind
}

/** 경로를 보여줄 참여자: 인덱스 하나, 전원('all'), 없음(null) */
export type RouteSelection = number | 'all' | null

/** overview: 출발지·추천 지역 전체 / focus: 선택한 지역(또는 경로)으로 확대 */
export type ViewMode = 'overview' | 'focus'
