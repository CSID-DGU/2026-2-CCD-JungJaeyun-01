export type AgeGroup = '10s' | '20s' | '30s' | '40s' | '50s+'
export type Purpose = 'meal' | 'cafe' | 'drink'

/** 출발지 자동완성 결과 (GET /api/search/places) */
export interface PlaceHit {
  id: string
  name: string
  address: string
  category: string
  lat: number
  lng: number
}

export interface RecommendRequest {
  participants: { name: string; lat: number; lng: number; age_group: AgeGroup }[]
  purpose: Purpose
}

export interface LatLng {
  lat: number
  lng: number
}

export interface RouteLeg {
  kind: 'walk' | 'subway' | 'bus'
  minutes: number
  distance_m: number
  label: string | null
  color: string | null
  from_name: string | null
  to_name: string | null
  stop_count: number | null
  /** 지도에 그릴 좌표 (출발 → 도착) */
  path: LatLng[]
}

export interface Route {
  total_minutes: number
  transfers: number
  legs: RouteLeg[]
}

export interface ParticipantTravel {
  name: string
  minutes: number
  /** true면 ODsay 조회에 실패해 거리 기반으로 추정한 값 */
  is_estimated: boolean
  /** 실제 대중교통 경로. 없으면 route_note에 이유가 있다 (가짜 경로는 만들지 않는다). */
  route: Route | null
  route_note: string | null
}

export interface Place {
  rank: number
  id: string
  name: string
  category: string
  address: string
  lat: number
  lng: number
  distance_m: number
  url: string
  phone: string
  score: number
  rating: number | null
  review_count: number | null
  age_fit_assumed: boolean
  reason: string
}

export interface Region {
  rank: number
  station: { id: string; name: string; lat: number; lng: number; lines: string[] }
  score: number
  reason: string
  metrics: { avg_minutes: number; max_minutes: number; std_minutes: number }
  participants: ParticipantTravel[]
  places: Place[]
}

export interface RecommendResponse {
  regions: Region[]
  meta: {
    purpose: Purpose
    evaluated_count: number
    estimated_travel: { station: string; participant: string; reason: string }[]
    age_preference: { source: string; is_assumed: boolean; note: string }
    place_warnings: string[]
  }
}
