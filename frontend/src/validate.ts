import type { AgeGroup, PlaceHit, RecommendRequest, Purpose } from './types'

export interface FormParticipant {
  key: number
  name: string
  age: AgeGroup
  origin: PlaceHit | null
}

export type FieldErrors = Record<number, { name?: string; origin?: string }>

export function validateParticipants(participants: FormParticipant[]): FieldErrors {
  const errors: FieldErrors = {}
  for (const p of participants) {
    const e: { name?: string; origin?: string } = {}
    if (!p.name.trim()) e.name = '이름을 입력해 주세요.'
    if (!p.origin) e.origin = '검색 결과에서 출발지를 선택해 주세요.'
    if (e.name || e.origin) errors[p.key] = e
  }
  return errors
}

/** 검증을 통과한 폼 값을 API 요청으로 바꾼다. */
export function toRequest(participants: FormParticipant[], purpose: Purpose, meetingTimeIso?: string): RecommendRequest {
  return {
    purpose,
    meeting_time: meetingTimeIso,
    participants: participants.map((p) => ({
      name: p.name.trim(),
      lat: p.origin!.lat,
      lng: p.origin!.lng,
      age_group: p.age,
    })),
  }
}
