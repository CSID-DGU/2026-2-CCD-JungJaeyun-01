import { useCallback, useMemo, useRef, useState } from 'react'
import { recommend } from './api'
import InputForm from './components/InputForm'
import MapView, { type OriginMarker } from './components/MapView'
import ResultPanel from './components/ResultPanel'
import { MAX_PARTICIPANTS, MIN_PARTICIPANTS, PARTICIPANT_COLORS } from './constants'
import type { MotionKind, MotionRequest, RouteSelection, ViewMode } from './map/types'
import type { Purpose, RecommendResponse } from './types'
import { toRequest, validateParticipants, type FieldErrors, type FormParticipant } from './validate'

const initialParticipants = (): FormParticipant[] => [
  { key: 1, name: '참여자 1', age: '20s', origin: null },
  { key: 2, name: '참여자 2', age: '20s', origin: null },
]

function App() {
  const nextKey = useRef(3)
  const motionId = useRef(0)
  const panelRef = useRef<HTMLElement>(null)
  const [participants, setParticipants] = useState<FormParticipant[]>(initialParticipants)
  const [purpose, setPurpose] = useState<Purpose>('meal')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [loading, setLoading] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [data, setData] = useState<RecommendResponse | null>(null)
  const [selectedRegion, setSelectedRegion] = useState(0)
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null)
  const [routeSelection, setRouteSelection] = useState<RouteSelection>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('overview')
  const [motion, setMotion] = useState<MotionRequest>({ id: 0, kind: 'none' })

  /** 지도에 "이번 동작의 이동·연출을 한 번 실행하라"고 알린다. */
  const bumpMotion = useCallback((kind: MotionKind) => {
    setMotion({ id: ++motionId.current, kind })
  }, [])

  // 지도에 넘기는 값은 참조가 안정적이어야 한다 (바뀔 때만 마커/범위를 다시 계산).
  const origins = useMemo<OriginMarker[]>(
    () =>
      participants.flatMap((p, i) =>
        p.origin
          ? [{ name: p.name.trim() || `참여자 ${i + 1}`, lat: p.origin.lat, lng: p.origin.lng, color: PARTICIPANT_COLORS[i] }]
          : [],
      ),
    [participants],
  )
  const regions = useMemo(() => data?.regions ?? [], [data])

  const selectRegion = useCallback(
    (index: number) => {
      setSelectedRegion(index)
      setSelectedPlaceId(null)
      setViewMode('focus')
      bumpMotion('region') // 선택된 참여자 경로는 유지되고 새 지역 기준으로 다시 그려진다
    },
    [bumpMotion],
  )

  const selectPlace = useCallback(
    (id: string | null) => {
      setSelectedPlaceId(id)
      if (id) setViewMode('focus')
      bumpMotion('place')
    },
    [bumpMotion],
  )

  const selectRoute = useCallback(
    (selection: RouteSelection) => {
      setRouteSelection(selection)
      if (selection !== null) setViewMode('focus')
      bumpMotion('route')
    },
    [bumpMotion],
  )

  const toggleView = useCallback(() => {
    setViewMode((mode) => (mode === 'overview' ? 'focus' : 'overview'))
    bumpMotion('view')
  }, [bumpMotion])

  function changeParticipant(key: number, patch: Partial<FormParticipant>) {
    setParticipants((list) => list.map((p) => (p.key === key ? { ...p, ...patch } : p)))
    setErrors((current) => {
      if (!current[key]) return current
      const next = { ...current }
      delete next[key]
      return next
    })
    if (patch.origin) bumpMotion('origins') // 출발지를 고르면 지도가 출발지들이 보이게 이동
  }

  function addParticipant() {
    setParticipants((list) =>
      list.length >= MAX_PARTICIPANTS
        ? list
        : [...list, { key: nextKey.current++, name: `참여자 ${list.length + 1}`, age: '20s', origin: null }],
    )
  }

  function removeParticipant(key: number) {
    setParticipants((list) => (list.length <= MIN_PARTICIPANTS ? list : list.filter((p) => p.key !== key)))
    setErrors({})
  }

  async function submit() {
    const found = validateParticipants(participants)
    setErrors(found)
    if (Object.keys(found).length > 0) {
      setSubmitError('입력하지 않은 항목이 있어요. 붉게 표시된 칸을 확인해 주세요.')
      return
    }
    setSubmitError(null)
    setLoading(true)
    try {
      const result = await recommend(toRequest(participants, purpose))
      setData(result)
      setSelectedRegion(0)
      setSelectedPlaceId(null)
      setRouteSelection(null)
      setViewMode('overview')
      bumpMotion('search') // 전체를 보여준 뒤 1·2·3위 마커가 순서대로 떨어진다
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : '추천을 가져오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <section className="map-area" aria-label="지도">
        <MapView
          origins={origins}
          regions={regions}
          selectedRegion={selectedRegion}
          selectedPlaceId={selectedPlaceId}
          routeSelection={routeSelection}
          viewMode={viewMode}
          motion={motion}
          obstacleRef={panelRef}
          onSelectRegion={selectRegion}
          onSelectPlace={selectPlace}
          onToggleView={toggleView}
        />
      </section>

      <aside className="panel" ref={panelRef}>
        {data ? (
          <ResultPanel
            data={data}
            selectedRegion={selectedRegion}
            selectedPlaceId={selectedPlaceId}
            routeSelection={routeSelection}
            onSelectRegion={selectRegion}
            onSelectPlace={selectPlace}
            onSelectRoute={selectRoute}
            onBack={() => {
              setData(null)
              setSelectedPlaceId(null)
              setRouteSelection(null)
              setViewMode('overview')
              bumpMotion('origins')
            }}
          />
        ) : (
          <InputForm
            participants={participants}
            purpose={purpose}
            errors={errors}
            loading={loading}
            submitError={submitError}
            onChangeParticipant={changeParticipant}
            onAdd={addParticipant}
            onRemove={removeParticipant}
            onPurpose={setPurpose}
            onSubmit={submit}
          />
        )}
      </aside>
    </div>
  )
}

export default App
