import type { RouteSegment } from './types'

/** 버스 노선명: 숫자·영문 번호는 "741번"처럼, 이미 이름이 있으면 그대로 */
export const busName = (name: string) => (/^[0-9A-Za-z-]+$/.test(name) ? `${name}번` : name)

/** 노선 배지에 쓰는 이름: 지하철은 "2호선", 버스는 버스 번호 */
export function lineLabel(seg: RouteSegment): string {
  if (!seg.lineName) return seg.mode === 'BUS' ? '버스' : '지하철'
  return seg.mode === 'BUS' ? busName(seg.lineName) : seg.lineName
}
