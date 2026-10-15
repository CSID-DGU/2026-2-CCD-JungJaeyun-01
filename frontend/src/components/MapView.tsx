/* eslint-disable @typescript-eslint/no-explicit-any */
import { placeKind } from '../categoryKind'
import { kakaoPlaceUrl } from '../links'
import { kindIconSvg, personIconSvg } from '../map/pinIcons'
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { MapPinOff } from 'lucide-react'
import { diagnoseKakaoMap } from '../api'
import StateMessage from './StateMessage'
import { loadKakaoMaps } from '../kakaoLoader'
import { buildDrawable, routePoints } from '../map/geometry'
import { MapMotion, computeFitTarget, prefersReducedMotion, type Padding } from '../map/motion'
import { RouteLayer } from '../map/routeLayer'
import type { MotionRequest, RouteSelection, SegmentFocus, ViewMode } from '../map/types'
import { routeKey, type RouteEntries } from '../routes'
import type { LatLng, Place, Region } from '../types'

const PLACE_COLORS = { meal: '#ff8a3d', cafe: '#9a6b46', drink: '#7c5cff' } as const

export interface OriginMarker {
  name: string
  lat: number
  lng: number
  color: string
}

interface Props {
  origins: OriginMarker[]
  regions: Region[]
  selectedRegion: number
  selectedPlaceId: string | null
  routeSelection: RouteSelection
  /** 이름을 눌러 불러온 참여자별 상세 경로 */
  routes: RouteEntries
  /** 타임라인에서 고른 구간 (그 구간만 강조하고 그 구간으로 이동) */
  segmentFocus: SegmentFocus | null
  /** 결과 직후 기본으로 펼친 경로를 그리라는 신호(증가할 때마다 한 번). 시점은 움직이지 않고 선만 그린다 */
  autoRouteTick?: number
  /** 지도에 경로 그리기를 시작하는 순간 알린다 (타임라인 등장 모션을 같은 시점에 시작하려고) */
  onRouteDrawStart?: (participants: number[], staggerMs: number) => void
  viewMode: ViewMode
  /** 연출을 일으킨 동작. id가 바뀔 때마다 해당 동작의 이동·연출을 한 번 실행한다. */
  motion: MotionRequest
  /** 지도 위에 겹쳐 보이는 패널이 있으면 그 폭만큼 왼쪽 여백을 더한다. */
  obstacleRef?: RefObject<HTMLElement | null>
  onSelectRegion: (index: number) => void
  onSelectPlace: (id: string | null) => void
  onToggleView: () => void
}

const APP_KEY = import.meta.env.VITE_KAKAO_JS_KEY ?? ''
const BASE_PADDING = 70
const DROP_STAGGER_MS = 120
const POP_STAGGER_MS = 60
const DRAW_MS = 600

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ESCAPES[c])

// ---- 카메라가 보여줄 좌표 묶음 ------------------------------------------------
const overviewPoints = (p: Props): LatLng[] => [...p.origins, ...p.regions.map((r) => r.station)]
const regionPoints = (p: Props): LatLng[] => {
  const region = p.regions[p.selectedRegion]
  return region ? [region.station, ...region.places] : []
}

/** 경로를 보여줄 참여자 인덱스 */
const selectedIndexes = (p: Props): number[] =>
  p.routeSelection === 'all' ? p.origins.map((_, i) => i) : p.routeSelection === null ? [] : [p.routeSelection]

function drawablesFor(p: Props) {
  const region = p.regions[p.selectedRegion]
  if (!region || p.origins.length !== region.participants.length) return []
  return selectedIndexes(p).flatMap((i) => {
    const entry = p.routes[routeKey(region.station.id, i)]
    return entry?.status === 'ok' ? [buildDrawable(entry.route, p.origins[i].color, i)] : []
  })
}

/** 선택한 참여자들의 경로(출발지에서 시작)와 도착역만 보이게 맞춘다. 선택하지 않은 참여자는 포함하지 않는다. */
const routeViewPoints = (p: Props): LatLng[] => {
  const region = p.regions[p.selectedRegion]
  return [...drawablesFor(p).flatMap(routePoints), ...(region ? [region.station] : [])]
}

export default function MapView(props: Props) {
  const { origins, regions, selectedRegion, selectedPlaceId, routeSelection, viewMode, motion } = props
  const { onSelectRegion, onSelectPlace, onToggleView, obstacleRef } = props
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<any>(null)
  const overlays = useRef<any[]>([])
  const elements = useRef(new Map<string, HTMLElement>())
  const infoWindow = useRef<any>(null)
  const motionCtl = useRef<MapMotion | null>(null)
  const routeLayer = useRef<RouteLayer | null>(null)
  const startedMotion = useRef(0)
  const lastFit = useRef<LatLng[] | null>(null)
  const latest = useRef(props)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    latest.current = props
  })

  const paddingFor = useCallback((): Padding => {
    // 패널이 지도를 가리는 레이아웃이면 가려지는 폭만큼 왼쪽 여백을 늘린다.
    let covered = 0
    const panel = obstacleRef?.current
    if (panel && box.current) {
      const a = panel.getBoundingClientRect()
      const b = box.current.getBoundingClientRect()
      const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left)
      const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
      if (overlapX > 0 && overlapY > 0) covered = overlapX
    }
    return { top: BASE_PADDING, right: BASE_PADDING, bottom: BASE_PADDING, left: BASE_PADDING + covered }
  }, [obstacleRef])

  // 1) SDK 로드 + 지도 생성 (한 번)
  useEffect(() => {
    let cancelled = false
    loadKakaoMaps(APP_KEY)
      .then((kakao) => {
        if (cancelled || !box.current || map.current) return
        map.current = new kakao.maps.Map(box.current, {
          center: new kakao.maps.LatLng(37.5665, 126.978),
          level: 8,
        })
        motionCtl.current = new MapMotion(map.current)
        routeLayer.current = new RouteLayer(map.current)
        setStatus('ready')
      })
      .catch(async (e: Error) => {
        // 브라우저는 실패 응답 본문을 읽을 수 없으므로 백엔드에 원인 진단을 요청한다.
        let message = e.message
        try {
          const diagnosis = await diagnoseKakaoMap()
          message =
            diagnosis.code !== 'ok'
              ? diagnosis.message
              : '서버에서는 SDK를 받을 수 있지만 브라우저에서 불러오지 못했습니다. 네트워크나 광고 차단 확장 프로그램을 확인해 주세요.'
        } catch {
          // 진단 API에 닿지 않으면 기본 안내를 보여준다.
        }
        if (cancelled) return
        setErrorMessage(message)
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 컨테이너 크기가 바뀌면 애니메이션 없이 즉시 다시 맞춘다.
  useEffect(() => {
    if (!box.current) return
    const observer = new ResizeObserver(() => {
      if (!map.current) return
      map.current.relayout()
      if (lastFit.current) motionCtl.current?.jump(computeFitTarget(map.current, lastFit.current, paddingFor()))
    })
    observer.observe(box.current)
    // 부모(지도 영역)와 창 크기가 바뀔 때, 폰트·레이아웃이 자리 잡은 직후에도 다시 맞춘다 (PC에서 타일이 밀리고 왼쪽·위에 빈 띠가 생기던 문제)
    if (box.current.parentElement) observer.observe(box.current.parentElement)
    const relayout = () => {
      if (!map.current) return
      map.current.relayout()
      if (lastFit.current) motionCtl.current?.jump(computeFitTarget(map.current, lastFit.current, paddingFor()))
    }
    window.addEventListener('resize', relayout)
    const timers = [100, 600, 1500].map((ms) => setTimeout(relayout, ms))
    void document.fonts?.ready.then(relayout)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', relayout)
      timers.forEach(clearTimeout)
    }
  }, [paddingFor, status])

  // 2) 마커 그리기. 연출이 예정된 마커는 'pre'(숨김)로 만들어 두었다가 이동이 끝난 뒤 보여준다.
  useEffect(() => {
    if (status !== 'ready') return
    const kakao = window.kakao
    overlays.current.forEach((o) => o.setMap(null))
    overlays.current = []
    elements.current.clear()
    const fresh = motion.id !== startedMotion.current
    const hideRegions = fresh && motion.kind === 'search'
    const hidePlaces = fresh && motion.kind === 'region'

    const addPin = (
      key: string,
      pos: LatLng,
      className: string,
      text: string,
      title: string,
      zIndex: number,
      extra: { onClick?: () => void; color?: string; iconSvg?: string; label?: string; badge?: string } = {},
    ) => {
      // .pin(끝이 뾰족한 핀 모양 상자) 안의 .pin-body 원에 내용이 들어간다. 선택 시 커지는 효과는 .pin-body에만 준다.
      const el = document.createElement('div')
      el.className = `pin ${className}`
      el.title = title
      const body = document.createElement('span')
      body.className = 'pin-body'
      if (extra.iconSvg) body.innerHTML = extra.iconSvg
      else body.textContent = text
      el.appendChild(body)
      if (extra.label) {
        // 출발지 핀 옆에 이름표를 붙여 추천 장소 핀과 한눈에 구별되게 한다
        const tag = document.createElement('span')
        tag.className = 'pin-label'
        tag.textContent = extra.label
        el.appendChild(tag)
      }
      if (extra.badge) {
        const b = document.createElement('b')
        b.className = 'pin-rank'
        b.textContent = extra.badge
        el.appendChild(b)
      }
      if (extra.color) el.style.setProperty('--pin-color', extra.color)
      if (extra.onClick) el.addEventListener('click', extra.onClick)
      const overlay = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(pos.lat, pos.lng),
        content: el,
        xAnchor: 0.5,
        yAnchor: 1,
        zIndex,
      })
      overlay.setMap(map.current)
      overlays.current.push(overlay)
      elements.current.set(key, el)
    }

    // 이름 첫 글자가 서로 다르면 첫 글자, 겹치면(예: 참여자 1·2·3) 순번으로 표시한다.
    const initials = origins.map((o) => [...o.name][0] ?? '')
    const unique = new Set(initials).size === initials.length
    origins.forEach((o, i) =>
      addPin(`origin-${i}`, o, 'pin-origin', unique ? initials[i] : String(i + 1), `${o.name} 출발지`, 3, {
        color: o.color,
        iconSvg: personIconSvg(20), // 참여자는 사람 아이콘 + 참여자 색, 추천 지역은 순위 숫자라서 한눈에 구별된다
        label: o.name,
      }),
    )
    regions.forEach((r, i) =>
      addPin(
        `region-${i}`,
        r.station,
        `pin-region${i === selectedRegion ? ' active' : ''}${hideRegions ? ' pre' : ''}`,
        String(r.rank),
        `${r.rank}위 ${r.station.name}`,
        i === selectedRegion ? 6 : 5,
        { onClick: () => onSelectRegion(i) },
      ),
    )
    // 경로를 볼 때는 지도가 넓게 축소되어 장소 마커가 지역 번호를 덮으므로 숨긴다.
    if (viewMode === 'focus' && routeSelection === null) {
      regions[selectedRegion]?.places.forEach((p) => {
        const active = p.id === selectedPlaceId
        addPin(
          `place-${p.id}`,
          p,
          `pin-place${active ? ' active' : ''}${hidePlaces ? ' pre' : ''}`,
          '',
          p.name,
          active ? 9 : 7,
          { onClick: () => onSelectPlace(p.id), iconSvg: kindIconSvg(placeKind(p), 16), color: PLACE_COLORS[placeKind(p)], badge: String(p.rank) },
        )
      })
    }
  }, [status, origins, regions, selectedRegion, selectedPlaceId, routeSelection, viewMode, motion.id, motion.kind, onSelectRegion, onSelectPlace])

  // 2-1) 결과 직후 기본 경로: 카메라 이동(검색 연출)을 끊지 않도록 별도 신호로 선만 그린다. 시점은 참여자 전원 + 추천 지역이 다 보이는 그대로.
  const autoTick = props.autoRouteTick ?? 0
  useEffect(() => {
    const routes = routeLayer.current
    const p = latest.current
    if (status !== 'ready' || autoTick === 0 || !routes || p.routeSelection === null) return
    const drawables = drawablesFor(p)
    const stagger = drawables.length > 1 ? Math.min(200, 400 / (drawables.length - 1)) : 0
    routes.clear()
    p.onRouteDrawStart?.(drawables.map((d) => d.participant), stagger)
    void routes.draw(drawables, { animate: !prefersReducedMotion(), durationMs: DRAW_MS, staggerMs: stagger })
  }, [autoTick, status])

  // 3) 동작별 이동과 연출. 이동이 끝난 뒤에 연출을 시작하고, 새 동작이 오면 이전 이동은 취소한다.
  useEffect(() => {
    const ctl = motionCtl.current
    const routes = routeLayer.current
    if (status !== 'ready' || !ctl || !routes || motion.id === 0) return
    startedMotion.current = motion.id
    let cancelled = false
    const alive = () => !cancelled
    const reduced = prefersReducedMotion()
    const el = (key: string) => elements.current.get(key)
    const closeInfo = () => {
      infoWindow.current?.close()
      infoWindow.current = null
    }

    const fit = async (points: LatLng[]) => {
      lastFit.current = points
      await ctl.whenIdle()
      if (!alive()) return false
      const ok = await ctl.moveTo(computeFitTarget(map.current, points, paddingFor()))
      if (ok && alive() && points.length > 1) {
        // 마지막 확인: 점이 하나라도 화면 밖이면(애니메이션이 겹쳐 일부가 무시된 경우) 애니메이션 없이 다시 맞춘다.
        const kakao = window.kakao
        const bounds = map.current.getBounds()
        if (points.some((q) => !bounds.contain(new kakao.maps.LatLng(q.lat, q.lng)))) {
          ctl.jump(computeFitTarget(map.current, points, paddingFor()))
        }
      }
      return ok && alive()
    }
    const show = (e: HTMLElement | undefined) => e?.classList.remove('pre')
    const animate = (e: HTMLElement | undefined, cls: string, delayMs: number, clearAfterMs: number) => {
      if (!e) return
      show(e)
      if (reduced) return
      e.style.setProperty('--d', `${delayMs}ms`)
      e.classList.add(cls)
      setTimeout(() => e.classList.remove(cls), clearAfterMs)
    }
    const dropRegions = (count: number) =>
      Array.from({ length: count }, (_, i) => animate(el(`region-${i}`), 'drop', i * DROP_STAGGER_MS, 1200))
    const pulse = (index: number) => animate(el(`region-${index}`), 'pulse', 0, 1000)
    const popPlaces = (region: Region | undefined) =>
      region?.places.forEach((p, i) => animate(el(`place-${p.id}`), 'pop', i * POP_STAGGER_MS, 900))

    const drawRoutes = async (p: Props) => {
      const drawables = drawablesFor(p)
      const stagger = drawables.length > 1 ? Math.min(200, 400 / (drawables.length - 1)) : 0
      p.onRouteDrawStart?.(drawables.map((d) => d.participant), stagger)
      await routes.draw(drawables, { animate: !reduced, durationMs: DRAW_MS, staggerMs: stagger })
    }

    const openInfo = (place: Place) => {
      const kakao = window.kakao
      const rating =
        place.rating != null
          ? `★ ${place.rating.toFixed(1)} (리뷰 ${place.review_count?.toLocaleString()}개)`
          : '평점 정보 없음'
      const link = `<a href="${esc(kakaoPlaceUrl(place))}" target="_blank" rel="noopener">카카오맵에서 보기</a>`
      infoWindow.current = new kakao.maps.InfoWindow({
        position: new kakao.maps.LatLng(place.lat, place.lng),
        removable: true,
        zIndex: 20,
        content: `<div class="iw"><strong>${esc(place.name)}</strong><span>${esc(rating)}</span>${link}</div>`,
      })
      infoWindow.current.open(map.current)
    }

    const run = async () => {
      const p = latest.current
      const region = p.regions[p.selectedRegion]
      if (motion.kind === 'none') return
      if (motion.kind !== 'place') closeInfo()

      switch (motion.kind) {
        case 'origins': // 입력 화면: 출발지가 모두 보이게
          routes.clear()
          await fit(p.origins)
          break
        case 'search': // 검색 완료: 전체를 보여준 뒤 1·2·3위 마커가 순서대로 떨어진다
          routes.clear()
          if (await fit(overviewPoints(p))) dropRegions(p.regions.length)
          break
        case 'region': // 지역 탭 전환: 그 지역으로 이동 → 펄스 + Top 5 팝업, 선택된 경로는 새 지역 기준으로 다시 그림
          routes.clear()
          if (p.routeSelection !== null) {
            if (!(await fit(routeViewPoints(p)))) return
            pulse(p.selectedRegion)
            await drawRoutes(p)
          } else {
            if (!(await fit(regionPoints(p)))) return
            pulse(p.selectedRegion)
            popPlaces(region)
          }
          break
        case 'place': {
          closeInfo()
          const place = region?.places.find((x) => x.id === p.selectedPlaceId)
          if (!place) return
          lastFit.current = [place]
          const kakao = window.kakao
          const level = Math.min(map.current.getLevel(), 3)
          const moved = await ctl.moveTo({ center: new kakao.maps.LatLng(place.lat, place.lng), level })
          if (!moved || !alive()) return
          animate(el(`place-${place.id}`), 'bounce', 0, 700)
          openInfo(place)
          break
        }
        case 'route': // 참여자 클릭/모두 보기: 경로 전체가 보이게 이동 → 선이 그려진다
          routes.clear()
          if (p.routeSelection === null) return
          if (!(await fit(routeViewPoints(p)))) return
          await drawRoutes(p)
          break
        case 'segment': { // 타임라인의 구간 클릭: 그 구간만 강조하고 그 구간으로 이동 (다시 누르면 경로 전체로)
          const focus = p.segmentFocus
          if (!focus) {
            routes.highlight(null, null)
            await fit(routeViewPoints(p))
            break
          }
          const leg = drawablesFor(p).find((d) => d.participant === focus.participant)?.legs[focus.segment]
          if (!leg) break
          routes.highlight(focus.participant, focus.segment)
          await fit(leg.path)
          break
        }
        case 'view': // 전체 보기 ↔ 선택 지역 확대
          await fit(
            p.viewMode === 'overview'
              ? overviewPoints(p)
              : p.routeSelection !== null
                ? routeViewPoints(p)
                : regionPoints(p),
          )
          break
      }
    }
    void run()
    return () => {
      cancelled = true
      ctl.cancel()
    }
  }, [status, motion.id, motion.kind, paddingFor])

  return (
    <div className="map-box">
      <div ref={box} className="map" />
      {status === 'ready' && (origins.length > 0 || regions.length > 0) && (
        <ul className="map-legend" aria-label="지도 범례">
          <li><i className="lg lg-origin" />출발지</li>
          {regions.length > 0 && <li><i className="lg lg-region" />추천 지역</li>}
          {regions.length > 0 && <li><i className="lg lg-place" />추천 장소</li>}
        </ul>
      )}
      {status === 'ready' && regions.length > 0 && (
        <button type="button" className="map-toggle" onClick={onToggleView}>
          {viewMode === 'overview' ? '선택 지역 확대' : '전체 보기'}
        </button>
      )}
      {status === 'loading' && <div className="map-note">지도를 불러오는 중…</div>}
      {status === 'error' && (
        <div className="map-note error" role="alert">
          <StateMessage Icon={MapPinOff} tone="error" title="지도를 불러오지 못했어요">{errorMessage}</StateMessage>
        </div>
      )}
    </div>
  )
}
