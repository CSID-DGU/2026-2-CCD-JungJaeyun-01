/* eslint-disable @typescript-eslint/no-explicit-any */
// 지도 카메라 이동: 목표를 먼저 계산하고(화면 깜빡임 없이), 거리에 따라 단계적으로 이동한다.
import type { LatLng } from '../types'

export interface Padding {
  top: number
  right: number
  bottom: number
  left: number
}

export interface FitTarget {
  center: any // kakao.maps.LatLng
  level: number
}

const MIN_FIT_LEVEL = 3 // 이보다 더 확대하지 않는다
const SINGLE_POINT_LEVEL = 4
const ZOOM_OUT_MS = 250
const ZOOM_IN_MS = 350
const PAN_TIMEOUT_MS = 600

export const prefersReducedMotion = () =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/**
 * points가 패딩을 두고 모두 보이는 중심·레벨을 계산한다.
 * setBounds로 값을 읽은 뒤 같은 동기 구간 안에서 즉시 되돌리므로 화면이 한 번도 그려지지 않는다.
 */
export function computeFitTarget(map: any, points: LatLng[], padding: Padding): FitTarget {
  const kakao = window.kakao
  if (points.length === 0) return { center: new kakao.maps.LatLng(37.5665, 126.978), level: 8 }
  if (points.length === 1) {
    return { center: new kakao.maps.LatLng(points[0].lat, points[0].lng), level: SINGLE_POINT_LEVEL }
  }
  // 컨테이너 크기가 바뀐 직후에는 지도 내부 크기가 낡아서 setBounds 결과가 어긋난다 → 먼저 relayout.
  // (호출하는 쪽은 MapMotion.whenIdle()로 진행 중인 애니메이션이 끝난 뒤에 부른다.)
  map.relayout()
  const bounds = new kakao.maps.LatLngBounds()
  points.forEach((p) => bounds.extend(new kakao.maps.LatLng(p.lat, p.lng)))
  const prevCenter = map.getCenter()
  const prevLevel = map.getLevel()
  map.setBounds(bounds, padding.top, padding.right, padding.bottom, padding.left)
  const target = { center: map.getCenter(), level: Math.max(map.getLevel(), MIN_FIT_LEVEL) }
  map.setLevel(prevLevel)
  map.setCenter(prevCenter)
  return target
}

/** fn을 실행하고 지도가 idle이 될 때까지(또는 timeoutMs까지) 기다린다. */
function runAndWait(map: any, fn: () => void, timeoutMs: number): Promise<void> {
  const kakao = window.kakao
  return new Promise((resolve) => {
    let done = false
    const finish = () => {
      if (done) return
      done = true
      clearTimeout(timer)
      kakao.maps.event.removeListener(map, 'idle', finish)
      resolve()
    }
    const timer = setTimeout(finish, timeoutMs)
    kakao.maps.event.addListener(map, 'idle', finish)
    fn()
  })
}

export class MapMotion {
  private token = 0
  private map: any
  /** 가장 최근에 시작한 이동(취소된 것 포함)이 끝날 때까지의 약속 */
  private chain: Promise<unknown> = Promise.resolve()

  constructor(map: any) {
    this.map = map
  }

  /** 진행 중인 이동을 취소한다. */
  cancel() {
    this.token++
  }

  /** 애니메이션 없이 즉시 이동한다 (창 크기 변경, reduced-motion). */
  jump(target: FitTarget) {
    this.token++
    this.map.setLevel(target.level)
    this.map.setCenter(target.center)
  }

  private pixelDistance(center: any): number {
    const proj = this.map.getProjection()
    const a = proj.containerPointFromCoords(this.map.getCenter())
    const b = proj.containerPointFromCoords(center)
    return Math.hypot(a.x - b.x, a.y - b.y)
  }

  /**
   * 진행 중이던 이동·확대 애니메이션이 끝날 때까지 기다린다(최대 1.5초).
   * 애니메이션 도중에 setBounds로 목표를 계산하면 옛 레벨이 나와서 지도가 엉뚱한 곳에 멈춘다.
   */
  async whenIdle(): Promise<void> {
    await Promise.race([this.chain, new Promise((r) => setTimeout(r, 1500))])
  }

  /**
   * 목표가 화면 밖이면: 한 단계 축소 → 이동 → 목표 레벨까지 확대.
   * 화면 안이면: 이동 → 확대만. 이동 중 새 요청이 오면 이전 이동은 멈추고 false를 돌려준다.
   */
  moveTo(target: FitTarget): Promise<boolean> {
    if (prefersReducedMotion()) {
      this.jump(target)
      return Promise.resolve(true)
    }
    const run = this.animateTo(target)
    this.chain = run.catch(() => false)
    return run
  }

  private async animateTo(target: FitTarget): Promise<boolean> {
    const my = ++this.token
    const map = this.map
    const alive = () => this.token === my

    const level = map.getLevel()
    const far = !map.getBounds().contain(target.center)
    if (far && level < 14) {
      await runAndWait(map, () => map.setLevel(level + 1, { animate: { duration: ZOOM_OUT_MS } }), ZOOM_OUT_MS + 150)
      if (!alive()) return false
    }
    if (this.pixelDistance(target.center) > 4) {
      await runAndWait(map, () => map.panTo(target.center), PAN_TIMEOUT_MS)
      if (!alive()) return false
    }
    if (map.getLevel() !== target.level) {
      await runAndWait(map, () => map.setLevel(target.level, { animate: { duration: ZOOM_IN_MS } }), ZOOM_IN_MS + 150)
      if (!alive()) return false
    }
    // 앞선 애니메이션이 아직 도는 중에 시작하면 카카오 지도가 이동·확대 일부를 무시하는 일이 있다.
    // 끝났는데도 목표와 다르면(레벨이 다르거나 중심이 어긋남) 애니메이션 없이 정확히 맞춘다.
    this.settle(target, my)
    setTimeout(() => this.settle(target, my), 400) // 늦게 끝난 이전 애니메이션이 덮어쓴 경우도 바로잡는다
    return true
  }

  private settle(target: FitTarget, my: number) {
    if (this.token !== my) return
    if (this.map.getLevel() !== target.level) this.map.setLevel(target.level)
    if (this.pixelDistance(target.center) > 4) this.map.setCenter(target.center)
  }
}
