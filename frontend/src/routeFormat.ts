import type { Route, RouteSegment } from './types'

/** 버스 노선명: 숫자·영문 번호는 "741번"처럼, 이미 이름이 있으면 그대로 */
export const busName = (name: string) => (/^[0-9A-Za-z-]+$/.test(name) ? `${name}번` : name)

/** 노선 배지에 쓰는 이름: 지하철은 "2호선", 버스는 버스 번호 */
export function lineLabel(seg: RouteSegment): string {
  if (!seg.lineName) return seg.mode === 'BUS' ? '버스' : '지하철'
  return seg.mode === 'BUS' ? busName(seg.lineName) : seg.lineName
}

/**
 * 구간별 분(정수)을 만든다. 합이 항상 route.totalMinutes와 같아서
 * 막대 안 글자, 타임라인, 요약의 숫자가 서로 어긋나지 않는다. 화면의 소요시간은 이 값 하나만 쓴다.
 */
export function fitMinutes(route: Pick<Route, 'segments' | 'totalMinutes'>): number[] {
  const raw = route.segments.map((s) => Math.max(s.minutes, 0.5))
  const sum = raw.reduce((a, b) => a + b, 0)
  const total = Math.max(route.totalMinutes, raw.length)
  const scaled = raw.map((m) => (m / sum) * total)
  const out = scaled.map((m) => Math.max(1, Math.floor(m)))
  let diff = total - out.reduce((a, b) => a + b, 0)
  const order = scaled.map((m, i) => ({ i, r: m - Math.floor(m) })).sort((a, b) => b.r - a.r)
  for (let k = 0; diff > 0; diff--, k++) out[order[k % order.length].i]++
  while (diff < 0) {
    const i = out.indexOf(Math.max(...out))
    if (out[i] <= 1) break
    out[i]--
    diff++
  }
  return out
}
