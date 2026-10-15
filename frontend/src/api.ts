import type { PlaceHit, RecommendRequest, RecommendResponse, RouteResponse } from './types'

const NETWORK_ERROR = '서버에 연결할 수 없습니다. 백엔드(localhost:8000)가 실행 중인지 확인해 주세요.'

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return '입력값이 올바르지 않습니다. 이름과 출발지를 확인해 주세요.'
  } catch {
    // 본문이 JSON이 아니면 상태 코드로 안내한다.
  }
  return `서버 오류가 발생했습니다 (HTTP ${res.status}).`
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new Error(NETWORK_ERROR)
  }
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json() as Promise<T>
}

/** 출발지 자동완성: 백엔드가 카카오 키워드 검색을 대신 호출한다. */
export function searchPlaces(query: string, signal: AbortSignal): Promise<PlaceHit[]> {
  return request(`/api/search/places?query=${encodeURIComponent(query)}`, { signal })
}

export interface MapDiagnosis {
  code: string
  message: string
}

/** 지도 SDK 로드에 실패했을 때, 백엔드가 원인(도메인 미등록/키 오류/카카오맵 미사용 설정)을 알려준다. */
export function diagnoseKakaoMap(): Promise<MapDiagnosis> {
  return request(`/api/diagnostics/kakao-map?origin=${encodeURIComponent(window.location.origin)}`)
}

export function recommend(body: RecommendRequest): Promise<RecommendResponse> {
  return request('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** 참여자 한 명의 상세 경로. 사용자가 이름을 눌렀을 때만 호출한다 (백엔드가 캐시). */
export function fetchRoute(lat: number, lng: number, stationId: string, meetingTime?: string): Promise<RouteResponse> {
  return request('/api/route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lng, station_id: stationId, meeting_time: meetingTime }),
  })
}

export interface UsageInfo {
  day: string
  provider: string
  mode: string
  counters: Record<string, number>
}

/** 개발용: 오늘 경로 API 호출 수 */
export function fetchUsage(): Promise<UsageInfo> {
  return request('/api/dev/usage')
}

export interface AuthState {
  loggedIn: boolean
  nickname: string | null
}

/** 로그인 상태. 토큰은 받지 않는다 (httpOnly 세션 쿠키만 오간다). */
export function fetchMe(): Promise<AuthState> {
  return request('/auth/me')
}

export function logout(): Promise<AuthState> {
  return request('/auth/logout', { method: 'POST' })
}

/** 나에게 보내기 (로그인 필요) */
export function sendMemo(text: string, url: string): Promise<{ sent: boolean }> {
  return request('/api/share/memo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, url }),
  })
}

export interface Arrival {
  /** 도착까지 남은 시간(초). 모르면 null */
  seconds: number | null
  /** 몇 정거장 전. 모르면 null */
  stopsAway: number | null
  text: string
  destination: string | null
}

export type RealtimeQuery =
  | { type: 'subway'; station: string; line: string; headsign: string | null; next: string | null }
  | { type: 'bus'; stop: string; line: string; lat: number; lng: number }

export interface RealtimeResponse {
  available: boolean
  items: Arrival[]
  /** epoch 초 */
  updatedAt: number
}

/** 다음 열차/버스 도착 정보. 실패해도 오류가 아니라 available=false로 온다. */
export function fetchRealtime(q: RealtimeQuery, signal?: AbortSignal): Promise<RealtimeResponse> {
  const p = new URLSearchParams({ type: q.type, line: q.line })
  if (q.type === 'subway') {
    p.set('station', q.station)
    if (q.headsign) p.set('headsign', q.headsign)
    if (q.next) p.set('next', q.next)
  } else {
    p.set('stop', q.stop)
    p.set('lat', String(q.lat))
    p.set('lng', String(q.lng))
  }
  return request(`/api/realtime?${p}`, { signal })
}
