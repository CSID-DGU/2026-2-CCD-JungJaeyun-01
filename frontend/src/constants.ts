import type { AgeGroup, Purpose } from './types'

export const AGE_OPTIONS: { value: AgeGroup; label: string }[] = [
  { value: '10s', label: '10대' },
  { value: '20s', label: '20대' },
  { value: '30s', label: '30대' },
  { value: '40s', label: '40대' },
  { value: '50s+', label: '50대 이상' },
]

export const PURPOSE_OPTIONS: { value: Purpose; label: string }[] = [
  { value: 'meal', label: '식사' },
  { value: 'cafe', label: '카페' },
  { value: 'drink', label: '술자리' },
]

export const MIN_PARTICIPANTS = 2
export const MAX_PARTICIPANTS = 5

/** 참여자 구분 색. 카드, 지도 출발지 마커, 이동시간 막대에서 같은 색을 쓴다. */
export const PARTICIPANT_COLORS = ['#e4572e', '#2e86de', '#17a672', '#8e44ad', '#d68910']
