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

export interface ParticipantTravel {
  name: string
  minutes: number
  /** true면 ODsay 조회에 실패해 거리 기반으로 추정한 값 */
  is_estimated: boolean
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
