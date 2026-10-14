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
  participant: number
  weights: number[]
  route: DrawableRoute
  polylines: any[]
  legStart: number[]
  legLen: number[]
  total: number
  dots: { el: HTMLElement; at: number }[] // 환승 점, 버스 아이콘
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
  private states: RouteState[] = []
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
    this.states = []
  }

  /**
   * 타임라인에서 고른 구간만 굵고 진하게, 나머지(다른 참여자 포함)는 흐리게 보여준다. 둘 다 null이면 원래대로.
   */
  highlight(participant: number | null, legIndex: number | null) {
    const on = participant !== null && legIndex !== null
    for (const st of this.states) {
      st.polylines.forEach((polyline, i) => {
        const focused = on && st.participant === participant && i === legIndex
        polyline.setOptions({
          strokeOpacity: !on ? 0.92 : focused ? 1 : 0.2,
          strokeWeight: focused ? st.weights[i] + 3 : st.weights[i],
        })
      })
    }
  }

  /** 모두 그려지면(또는 취소되면) resolve. */
  draw(routes: DrawableRoute[], opts: DrawOptions): Promise<void> {
    this.clear()
    const my = this.token
    const states: RouteState[] = routes.map((route) => this.build(route, opts.animate))
    this.states = states
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

    const dots: { el: HTMLElement; at: number }[] = route.transfers.map((point) => {
      const el = document.createElement('div')
      el.className = `pin-transfer${animate ? ' pre' : ''}`
      el.style.borderColor = route.color
      this.items.push(overlayAt(this.map, point, el, 4))
      // 환승 지점까지의 누적 거리: 해당 지점이 시작인 구간의 legStart
      const idx = route.legs.findIndex((leg) => leg.path[0] === point)
      return { el, at: idx >= 0 ? legStart[idx] : 0 }
    })

    // 버스는 지하철처럼 노선 색 실선으로 그리고, 타는 지점에 버스 아이콘을 붙인다.
    route.busBoardings.forEach(({ legIndex, point, color }) => {
      const el = document.createElement('div')
      el.className = `pin-bus${animate ? ' pre' : ''}`
      el.textContent = '🚌'
      el.style.borderColor = color
      this.items.push(overlayAt(this.map, point, el, 4))
      dots.push({ el, at: legStart[legIndex] })
    })

    if (route.estimatedLabel) {
      // 가장 긴 구간의 가운데에 "추정 경로" 라벨을 붙인다.
      const longest = route.legs.reduce((a, b) => (b.path.length > a.path.length ? b : a))
      const mid = longest.path[Math.floor(longest.path.length / 2)]
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
    return {
      participant: route.participant, weights: route.legs.map((leg) => leg.weight),
      route, polylines, legStart, legLen, total, dots, follower, finished: false,
    }
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
