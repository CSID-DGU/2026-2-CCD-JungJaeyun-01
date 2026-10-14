/* eslint-disable @typescript-eslint/no-explicit-any */
// 참여자 경로를 지도에 그린다. 선이 출발지에서 도착지 방향으로 점점 그려지고, 끝에 작은 점이 따라간다.
import type { LatLng } from '../types'
import { partialPath, pathLengthM, type DrawableRoute } from './geometry'

export interface DrawOptions {
  animate: boolean
  durationMs: number
  /** 참여자마다 시작을 늦추는 간격 */
  staggerMs: number
}

interface RouteState {
  route: DrawableRoute
  polylines: any[]
  legStart: number[]
  legLen: number[]
  total: number
  dots: { el: HTMLElement; at: number }[]
  follower: any | null
  finished: boolean
}

const ll = (p: LatLng) => new window.kakao.maps.LatLng(p.lat, p.lng)

function overlayAt(map: any, point: LatLng, el: HTMLElement, zIndex: number) {
  const overlay = new window.kakao.maps.CustomOverlay({
    position: ll(point), content: el, xAnchor: 0.5, yAnchor: 0.5, zIndex,
  })
  overlay.setMap(map)
  return overlay
}

export class RouteLayer {
  private items: any[] = [] // setMap(null)로 지울 수 있는 폴리라인·오버레이
  private raf = 0
  private token = 0
  private map: any

  constructor(map: any) {
    this.map = map
  }

  clear() {
    this.token++
    cancelAnimationFrame(this.raf)
    this.items.forEach((item) => item.setMap(null))
    this.items = []
  }

  /** 모두 그려지면(또는 취소되면) resolve. */
  draw(routes: DrawableRoute[], opts: DrawOptions): Promise<void> {
    this.clear()
    const my = this.token
    const states: RouteState[] = routes.map((route) => this.build(route, opts.animate))
    if (!opts.animate) return Promise.resolve()

    return new Promise((resolve) => {
      const start = performance.now()
      const frame = (now: number) => {
        if (this.token !== my) return resolve()
        let allDone = true
        states.forEach((st, k) => {
          const t = Math.min(1, Math.max(0, (now - start - k * opts.staggerMs) / opts.durationMs))
          if (t < 1) allDone = false
          this.update(st, t * st.total, t)
        })
        if (allDone) return resolve()
        this.raf = requestAnimationFrame(frame)
      }
      this.raf = requestAnimationFrame(frame)
    })
  }

  private build(route: DrawableRoute, animate: boolean): RouteState {
    const kakao = window.kakao
    const legLen = route.legs.map((leg) => pathLengthM(leg.path))
    const legStart: number[] = []
    let total = 0
    legLen.forEach((len) => {
      legStart.push(total)
      total += len
    })

    const polylines = route.legs.map((leg) => {
      const polyline = new kakao.maps.Polyline({
        map: this.map,
        path: (animate ? [leg.path[0], leg.path[0]] : leg.path).map(ll),
        strokeWeight: leg.weight,
        strokeColor: leg.color,
        strokeOpacity: 0.92,
        strokeStyle: leg.dashed ? 'shortdash' : 'solid',
        zIndex: 2,
      })
      this.items.push(polyline)
      return polyline
    })

    const dots = route.transfers.map((point) => {
      const el = document.createElement('div')
      el.className = `pin-transfer${animate ? ' pre' : ''}`
      el.style.borderColor = route.color
      this.items.push(overlayAt(this.map, point, el, 4))
      // 환승 지점까지의 누적 거리: 해당 지점이 시작인 구간의 legStart
      const idx = route.legs.findIndex((leg) => leg.path[0] === point)
      return { el, at: idx >= 0 ? legStart[idx] : 0 }
    })

    if (route.estimatedLabel) {
      const first = route.legs[0].path
      const mid = { lat: (first[0].lat + first[1].lat) / 2, lng: (first[0].lng + first[1].lng) / 2 }
      const el = document.createElement('div')
      el.className = 'route-label'
      el.textContent = route.estimatedLabel
      this.items.push(overlayAt(this.map, mid, el, 5))
    }

    let follower: any = null
    if (animate) {
      const el = document.createElement('div')
      el.className = 'route-follower pre'
      el.style.background = route.color
      follower = overlayAt(this.map, route.legs[0].path[0], el, 6)
      this.items.push(follower)
    }
    return { route, polylines, legStart, legLen, total, dots, follower, finished: false }
  }

  private update(st: RouteState, d: number, t: number) {
    if (st.finished) return
    let head: LatLng = st.route.legs[0].path[0]
    st.route.legs.forEach((leg, i) => {
      const len = st.legLen[i]
      const local = d - st.legStart[i]
      const path = local <= 0 ? [leg.path[0], leg.path[0]] : local >= len ? leg.path : partialPath(leg.path, local)
      st.polylines[i].setPath(path.map(ll))
      if (local > 0) head = path[path.length - 1]
    })
    st.dots.forEach((dot) => d >= dot.at && dot.el.classList.remove('pre'))
    if (st.follower) {
      const el: HTMLElement = st.follower.getContent()
      if (t > 0 && t < 1) {
        el.classList.remove('pre')
        st.follower.setPosition(ll(head))
      }
      if (t >= 1) {
        // 도착하면 따라가던 점은 사라진다.
        st.follower.setMap(null)
        st.finished = true
        st.dots.forEach((dot) => dot.el.classList.remove('pre'))
      }
    }
  }
}
