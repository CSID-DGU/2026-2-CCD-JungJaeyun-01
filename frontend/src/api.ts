import type { PlaceHit, RecommendRequest, RecommendResponse } from './types'

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

export function recommend(body: RecommendRequest): Promise<RecommendResponse> {
  return request('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
