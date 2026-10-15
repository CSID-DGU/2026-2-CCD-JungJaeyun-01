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
  /** 약속 시간 (KST ISO 8601). 이 시각에 도착하는 기준으로 경로를 구한다. */
  meeting_time?: string
}

export interface LatLng {
  lat: number
  lng: number
}

/** 경로 API 종류와 무관한 공통 경로 스키마 (백엔드가 Google/ODsay/추정 결과를 이 형식으로 변환한다) */
export type RouteMode = 'WALK' | 'SUBWAY' | 'BUS'

export interface RouteSegment {
  mode: RouteMode
  lineName: string | null
  lineColor: string | null
  from: string | null
  to: string | null
  minutes: number
  /** [[lat, lng], ...] 출발 → 도착 */
  path: [number, number][]
  // --- 타임라인용 (모르면 null) ---
  distanceMeters: number | null
  /** KST ISO 8601 */
  departureTime: string | null
  arrivalTime: string | null
  /** "신도림역 방면" */
  headsign: string | null
  stopCount: number | null
  /** 노선 배지 글자색 */
  lineTextColor: string | null
  /** 경유 정거장 이름 (출발·도착 제외). Google은 주지 않아서 지하철만 노선도 데이터로 채운다. */
  intermediateStops: string[] | null
  intermediateStopsSource: 'subway-map' | null
  lineKind?: string | null
  /** 실시간 도착 정보를 붙일 때 쓰는 승·하차 정류장/노선/방면 참조 */
  realtime?: {
    boardStop: { name: string | null; lat: number | null; lng: number | null; id: string | null }
    alightStop: { name: string | null; lat: number | null; lng: number | null; id: string | null }
    line: { name: string | null; number: string | null; vehicleType: string | null }
    headsign: string | null
  } | null
}

export interface Route {
  totalMinutes: number
  transfers: number
  segments: RouteSegment[]
  /** google: 실제 경로 / estimate: 지하철 그래프 추정 경로 */
  source: 'google' | 'estimate' | 'odsay'
  /** 집을 나서는 시각 / 도착지 도착 시각 (KST ISO 8601, 추정 경로는 null) */
  departureTime: string | null
  arrivalTime: string | null
  walkMinutes: number | null
  walkMeters: number | null
}

export interface RouteResponse {
  route: Route
  /** 추정 경로일 때 이유 */
  note: string | null
}

export interface ParticipantTravel {
  name: string
  minutes: number
  /** true면 경로 API 확인에 실패해 1단계 추정값을 쓴 것 ("추정" 표시) */
  is_estimated: boolean
  estimate_minutes: number | null
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
  /** 1단계(지하철 그래프 추정) 순위. 최종 순위와 다르면 실제 경로(버스 포함)가 순위를 바꾼 것 */
  stage1_rank: number
  metrics: { avg_minutes: number; max_minutes: number; std_minutes: number }
  participants: ParticipantTravel[]
  places: Place[]
}

export interface Phase2 {
  status: 'ok' | 'failed' | 'skipped'
  reason: string | null
  provider: string | null
  api_calls: number
  cache_hits: number
  /** 경로 API로 확인한 후보 수 */
  candidates: number
}

export interface EstimateAccuracy {
  mae_minutes: number
  bias_minutes: number
  pairs: { participant: string; station: string; estimate_minutes: number; actual_minutes: number; diff_minutes: number }[]
}

export interface RecommendResponse {
  regions: Region[]
  meta: {
    purpose: Purpose
    candidate_count: number
    /** 실제로 쓴 약속 시간 (KST ISO 8601) */
    meeting_time: string
    travel_source: string
    phase2: Phase2
    estimate_accuracy: EstimateAccuracy | null
    age_preference: { source: string; is_assumed: boolean; note: string }
    place_warnings: string[]
  }
}
