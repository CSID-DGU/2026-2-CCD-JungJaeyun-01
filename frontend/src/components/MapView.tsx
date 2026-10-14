/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from 'react'
import { diagnoseKakaoMap } from '../api'
import { loadKakaoMaps } from '../kakaoLoader'
import type { Region } from '../types'

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
  onSelectRegion: (index: number) => void
  onSelectPlace: (id: string | null) => void
}

const APP_KEY = import.meta.env.VITE_KAKAO_JS_KEY ?? ''
const SEOUL = { lat: 37.5665, lng: 126.978 }

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ESCAPES[c])

export default function MapView(props: Props) {
  const { origins, regions, selectedRegion, selectedPlaceId, onSelectRegion, onSelectPlace } = props
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<any>(null)
  const overlays = useRef<any[]>([])
  const infoWindow = useRef<any>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('')
  // 결과 화면에서는 선택한 지역(역 + 추천 장소)으로 확대한다. 전체 보기는 지역/선택이 바뀌면 자동으로 풀린다.
  const [overviewOf, setOverviewOf] = useState<{ regions: Region[]; selected: number } | null>(null)
  const overview = overviewOf?.regions === regions && overviewOf.selected === selectedRegion
  const focusRegion = regions.length > 0 && !overview

  // 1) SDK 로드 + 지도 생성 (한 번)
  useEffect(() => {
    let cancelled = false
    loadKakaoMaps(APP_KEY)
      .then((kakao) => {
        if (cancelled || !box.current || map.current) return
        map.current = new kakao.maps.Map(box.current, {
          center: new kakao.maps.LatLng(SEOUL.lat, SEOUL.lng),
          level: 8,
        })
        setStatus('ready')
      })
      .catch(async (e: Error) => {
        // 브라우저는 실패 응답 본문을 읽을 수 없으므로 백엔드에 원인 진단을 요청한다.
        let message = e.message
        try {
          const diagnosis = await diagnoseKakaoMap()
          if (diagnosis.code !== 'ok') message = diagnosis.message
          else message = '서버에서는 SDK를 받을 수 있지만 브라우저에서 불러오지 못했습니다. 네트워크나 광고 차단 확장 프로그램을 확인해 주세요.'
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

  // 컨테이너 크기가 바뀌면 (모바일 회전, 패널 전환) 지도를 다시 맞춘다.
  useEffect(() => {
    if (!box.current) return
    const observer = new ResizeObserver(() => map.current?.relayout())
    observer.observe(box.current)
    return () => observer.disconnect()
  }, [])

  // 2) 마커 그리기
  useEffect(() => {
    if (status !== 'ready') return
    const kakao = window.kakao
    overlays.current.forEach((o) => o.setMap(null))
    overlays.current = []

    const addPin = (
      lat: number,
      lng: number,
      className: string,
      text: string,
      title: string,
      zIndex: number,
      onClick?: () => void,
      color?: string,
    ) => {
      const el = document.createElement('div')
      el.className = `pin ${className}`
      el.textContent = text
      el.title = title
      if (color) el.style.background = color
      if (onClick) el.addEventListener('click', onClick)
      const overlay = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(lat, lng),
        content: el,
        xAnchor: 0.5,
        yAnchor: 0.5,
        zIndex,
      })
      overlay.setMap(map.current)
      overlays.current.push(overlay)
    }

    // 이름 첫 글자가 서로 다르면 첫 글자, 겹치면(예: 참여자 1·2·3) 순번으로 표시한다.
    const initials = origins.map((o) => [...o.name][0] ?? '')
    const unique = new Set(initials).size === initials.length
    origins.forEach((o, i) =>
      addPin(o.lat, o.lng, 'pin-origin', unique ? initials[i] : String(i + 1), `${o.name} 출발지`, 3, undefined, o.color),
    )
    regions.forEach((r, i) =>
      addPin(
        r.station.lat,
        r.station.lng,
        `pin-region${i === selectedRegion ? ' active' : ''}`,
        String(r.rank),
        `${r.rank}위 ${r.station.name}`,
        i === selectedRegion ? 6 : 5,
        () => onSelectRegion(i),
      ),
    )
    regions[selectedRegion]?.places.forEach((p) => {
      const active = p.id === selectedPlaceId
      addPin(p.lat, p.lng, `pin-place${active ? ' active' : ''}`, '', p.name, active ? 9 : 7, () =>
        onSelectPlace(p.id),
      )
    })
  }, [status, origins, regions, selectedRegion, selectedPlaceId, onSelectRegion, onSelectPlace])

  // 3) 범위 자동 조정: 장소 선택만 바뀔 때는 움직이지 않는다.
  useEffect(() => {
    if (status !== 'ready') return
    const kakao = window.kakao
    const selected = regions[selectedRegion]
    const points: { lat: number; lng: number }[] = focusRegion
      ? [selected.station, ...selected.places]
      : [...origins, ...regions.map((r) => r.station)]
    if (points.length === 0) {
      map.current.setCenter(new kakao.maps.LatLng(SEOUL.lat, SEOUL.lng))
      map.current.setLevel(8)
    } else if (points.length === 1) {
      map.current.setCenter(new kakao.maps.LatLng(points[0].lat, points[0].lng))
      map.current.setLevel(5)
    } else {
      const bounds = new kakao.maps.LatLngBounds()
      points.forEach((p) => bounds.extend(new kakao.maps.LatLng(p.lat, p.lng)))
      map.current.setBounds(bounds, 70, 70, 70, 70)
    }
  }, [status, origins, regions, selectedRegion, focusRegion])

  // 4) 선택한 장소의 정보창
  useEffect(() => {
    if (status !== 'ready') return
    infoWindow.current?.close()
    const place = regions[selectedRegion]?.places.find((p) => p.id === selectedPlaceId)
    if (!place) return
    const kakao = window.kakao
    const position = new kakao.maps.LatLng(place.lat, place.lng)
    const rating =
      place.rating != null ? `★ ${place.rating.toFixed(1)} (리뷰 ${place.review_count?.toLocaleString()}개)` : '평점 정보 없음'
    const link = /^https?:\/\//.test(place.url)
      ? `<a href="${esc(place.url)}" target="_blank" rel="noopener noreferrer">카카오맵에서 보기</a>`
      : ''
    infoWindow.current = new kakao.maps.InfoWindow({
      position,
      removable: true,
      content: `<div class="iw"><strong>${esc(place.name)}</strong><span>${esc(rating)}</span>${link}</div>`,
    })
    infoWindow.current.open(map.current)
    map.current.panTo(position)
  }, [status, regions, selectedRegion, selectedPlaceId])

  return (
    <div className="map-box">
      <div ref={box} className="map" />
      {status === 'ready' && regions.length > 0 && (
        <button
          type="button"
          className="map-toggle"
          onClick={() => setOverviewOf(overview ? null : { regions, selected: selectedRegion })}
        >
          {overview ? '선택 지역 확대' : '전체 보기'}
        </button>
      )}
      {status === 'loading' && <div className="map-note">지도를 불러오는 중…</div>}
      {status === 'error' && (
        <div className="map-note error" role="alert">
          <div>
            <strong>지도를 표시할 수 없어요</strong>
            <p>{errorMessage}</p>
          </div>
        </div>
      )}
    </div>
  )
}
