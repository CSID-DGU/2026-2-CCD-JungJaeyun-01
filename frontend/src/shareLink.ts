// 추천 입력값 ↔ URL 쿼리(?s=...) 변환, 공유 메시지 문구 만들기.
import { AGE_OPTIONS, MAX_PARTICIPANTS, MIN_PARTICIPANTS } from './constants'
import type { AgeGroup, Purpose, RecommendResponse } from './types'
import type { FormParticipant } from './validate'

export const SHARE_PARAM = 's'

interface Shared {
  v: 1
  /** [이름, 위도, 경도, 연령대, 출발지 이름, 출발지 주소] */
  p: [string, number, number, AgeGroup, string, string][]
  u: Purpose
  /** 약속 시간 'YYYY-MM-DDTHH:mm' (서울 시각) */
  t: string
}

export interface SharedInput {
  participants: FormParticipant[]
  purpose: Purpose
  meetingTime: string
}

const b64 = {
  enc: (s: string) => btoa(String.fromCharCode(...new TextEncoder().encode(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''),
  dec: (s: string) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0))),
}

/** 결과를 다시 볼 수 있는 주소. 입력값만 담고, 결과는 접속할 때 다시 계산한다. */
export function buildShareUrl(input: SharedInput, origin = window.location.origin): string {
  const payload: Shared = {
    v: 1,
    p: input.participants.map((p) => [p.name, p.origin!.lat, p.origin!.lng, p.age, p.origin!.name, p.origin!.address]),
    u: input.purpose,
    t: input.meetingTime,
  }
  return `${origin}/?${SHARE_PARAM}=${b64.enc(JSON.stringify(payload))}`
}

/** 주소의 ?s= 를 해석한다. 형식이 틀리거나 값이 이상하면 null (조용히 첫 화면으로 간다). */
export function parseShareParam(value: string | null): SharedInput | null {
  if (!value) return null
  try {
    const d = JSON.parse(b64.dec(value)) as Shared
    const ages = AGE_OPTIONS.map((o) => o.value)
    if (d.v !== 1 || !Array.isArray(d.p) || d.p.length < MIN_PARTICIPANTS || d.p.length > MAX_PARTICIPANTS) return null
    if (!['meal', 'cafe', 'drink'].includes(d.u) || typeof d.t !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(d.t)) return null
    const participants: FormParticipant[] = []
    for (const [i, row] of d.p.entries()) {
      const [name, lat, lng, age, placeName, address] = row
      if (typeof name !== 'string' || !Number.isFinite(lat) || !Number.isFinite(lng) || !ages.includes(age)) return null
      participants.push({
        key: i + 1, name: name.slice(0, 20), age,
        origin: { id: `shared-${i}`, name: String(placeName ?? ''), address: String(address ?? ''), category: '', lat, lng },
      })
    }
    return { participants, purpose: d.u, meetingTime: d.t }
  } catch {
    return null
  }
}

/** 카카오톡 메시지 본문 (카카오 text 템플릿 한도 200자). 1위 지역, 추천 장소 3곳, 참여자별 이동시간. */
export function buildShareText(data: RecommendResponse): string {
  const top = data.regions[0]
  const places = top.places.slice(0, 3).map((p) => p.name).join(', ')
  const times = top.participants.map((p) => `${p.name} ${Math.round(p.minutes)}분`).join(' · ')
  let text = `📍 모임 장소 1위: ${top.station.name}\n🍽 추천: ${places || '정보 없음'}\n🚇 ${times}`
  if (text.length > 200) text = `${text.slice(0, 199)}…`
  return text
}
