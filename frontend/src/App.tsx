import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchMe, fetchRoute, logout as apiLogout, recommend } from './api'
import AuthBar from './components/AuthBar'
import Intro from './components/Intro'
import Landing from './components/Landing'
import { shouldPlayIntro } from './introState'
import DevUsage from './components/DevUsage'
import InputForm from './components/InputForm'
import MapView, { type OriginMarker } from './components/MapView'
import ResultPanel from './components/ResultPanel'
import type { TimelinePlay } from './components/RouteTimeline'
import { MAX_PARTICIPANTS, MIN_PARTICIPANTS, PARTICIPANT_COLORS } from './constants'
import type { MotionKind, MotionRequest, RouteSelection, SegmentFocus, ViewMode } from './map/types'
import { defaultMeetingTime, isMeetingFarEnough, toMeetingIso } from './meeting'
import { routeKey, type RouteEntries, type RouteEntry } from './routes'
import { buildShareText, buildShareUrl, parseShareParam, SHARE_PARAM, type SharedInput } from './shareLink'
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
  const [meetingTime, setMeetingTime] = useState<string>(() => defaultMeetingTime()) // 다음 토요일 오후 6시
  const [meetingError, setMeetingError] = useState<string | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [loading, setLoading] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [data, setData] = useState<RecommendResponse | null>(null)
  const [selectedRegion, setSelectedRegion] = useState(0)
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null)
  const [routeSelection, setRouteSelection] = useState<RouteSelection>(null)
  const [segmentFocus, setSegmentFocus] = useState<SegmentFocus | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('overview')
  const [motion, setMotion] = useState<MotionRequest>({ id: 0, kind: 'none' })
  const [routes, setRoutes] = useState<RouteEntries>({})
  const [plays, setPlays] = useState<Record<string, TimelinePlay>>({})
  const [usageTick, setUsageTick] = useState(0)
  // 로그인 상태와 첫 화면. 비로그인도 추천 기능은 전부 쓸 수 있다.
  const [auth, setAuth] = useState<{ loaded: boolean; nickname: string | null }>({ loaded: false, nickname: null })
  const [stage, setStage] = useState<'landing' | 'app'>('landing')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<SharedInput | null>(null) // 결과를 만든 입력값 (공유 주소용)
  const [notice, setNotice] = useState<string | null>(null)
  const [introPlaying, setIntroPlaying] = useState(shouldPlayIntro) // 세션당 1번, reduced-motion이면 생략
  // 디버그 박스(경로 API 호출 수 등)는 주소에 ?debug=1이 있을 때만 보인다
  const [showDebug] = useState(() => new URLSearchParams(window.location.search).get('debug') === '1')
  const [autoRoute, setAutoRoute] = useState(0) // 결과 직후 기본 경로 그리기 신호 (지도 시점은 건드리지 않는다)
  const [liveMode, setLiveMode] = useState(false) // "지금 출발": 실시간 도착 정보 수동 켜기

  // 콜백(지도에 넘기는 안정적인 함수)이 항상 최신 값을 보도록 ref에 둔다.
  const latest = useRef({ participants, data, routeSelection, selectedRegion })
  useEffect(() => {
    latest.current = { participants, data, routeSelection, selectedRegion }
  })
  const routesRef = useRef<RouteEntries>({})
  const pending = useRef(new Map<string, Promise<void>>())
  const selectionToken = useRef(0)

  /** 지도에 "이번 동작의 이동·연출을 한 번 실행하라"고 알린다. */
  const bumpMotion = useCallback((kind: MotionKind) => {
    setMotion({ id: ++motionId.current, kind })
  }, [])

  const setEntry = useCallback((key: string, entry: RouteEntry) => {
    routesRef.current = { ...routesRef.current, [key]: entry }
    setRoutes(routesRef.current)
  }, [])

  const resetRoutes = useCallback(() => {
    routesRef.current = {}
    pending.current.clear()
    setRoutes({})
    setPlays({})
  }, [])

  /** 타임라인 등장 모션: 지도에서 이 참여자의 경로 그리기가 시작되는 순간에 맞춰 재생한다. */
  const onRouteDrawStart = useCallback((indexes: number[], staggerMs: number) => {
    const region = latest.current.data?.regions[latest.current.selectedRegion]
    if (!region) return
    const base = Date.now()
    setPlays((prev) => {
      const next = { ...prev }
      indexes.forEach((i, order) => {
        next[routeKey(region.station.id, i)] = { token: base + order, delayMs: order * staggerMs }
      })
      return next
    })
  }, [])

  /**
   * 선택한 참여자들의 상세 경로를 불러온다 (약속 시간 도착 기준). 이미 있거나 불러오는 중이면 재사용한다.
   * 1단계 추정값만 있는 참여자는 explicit(버튼)일 때만 불러온다 — 그 전에는 안내만 보여준다.
   */
  const ensureRoutes = useCallback(
    async (regionIndex: number, indexes: number[], explicit = false) => {
      const { data: current, participants: people } = latest.current
      const region = current?.regions[regionIndex]
      if (!current || !region) return
      const jobs = indexes.map((i) => {
        const key = routeKey(region.station.id, i)
        if (routesRef.current[key]?.status === 'ok') return Promise.resolve()
        if (region.participants[i]?.is_estimated && !explicit) return Promise.resolve()
        const inFlight = pending.current.get(key)
        if (inFlight) return inFlight
        const origin = people[i]?.origin
        if (!origin) return Promise.resolve()
        setEntry(key, { status: 'loading' })
        const job = fetchRoute(origin.lat, origin.lng, region.station.id, current.meta.meeting_time)
          .then((res) => {
            setEntry(key, { status: 'ok', route: res.route, note: res.note })
            // 지도에서 그리기가 시작되지 않더라도(이동이 취소된 경우 등) 타임라인이 영영 숨지 않도록
            setTimeout(() => setPlays((prev) => (prev[key] ? prev : { ...prev, [key]: { token: Date.now(), delayMs: 0 } })), 2500)
          })
          .catch((e: unknown) =>
            setEntry(key, { status: 'error', message: e instanceof Error ? e.message : '경로를 불러오지 못했어요.' }),
          )
          .finally(() => pending.current.delete(key))
        pending.current.set(key, job)
        return job
      })
      await Promise.all(jobs)
      setUsageTick((t) => t + 1)
    },
    [setEntry],
  )

  const indexesOf = (selection: RouteSelection): number[] =>
    selection === 'all' ? latest.current.participants.map((_, i) => i) : selection === null ? [] : [selection]

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
  const originInfos = useMemo(
    () => participants.map((p, i) => ({ name: p.name.trim() || `참여자 ${i + 1}`, address: p.origin?.address ?? p.origin?.name ?? '' })),
    [participants],
  )
  const regions = useMemo(() => data?.regions ?? [], [data])

  const selectRegion = useCallback(
    async (index: number) => {
      setSelectedRegion(index)
      setSelectedPlaceId(null)
      setSegmentFocus(null)
      setViewMode('focus')
      const selection = latest.current.routeSelection
      if (selection === null) {
        bumpMotion('region')
        return
      }
      // 경로가 선택된 상태에서 지역을 바꾸면 새 지역 기준 경로를 불러온 뒤 다시 그린다.
      const token = ++selectionToken.current
      await ensureRoutes(index, indexesOf(selection))
      if (token === selectionToken.current) bumpMotion('region')
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bumpMotion, ensureRoutes],
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
    async (selection: RouteSelection) => {
      const token = ++selectionToken.current
      setRouteSelection(selection)
      setSegmentFocus(null)
      if (selection === null) {
        bumpMotion('route')
        return
      }
      setViewMode('focus')
      latest.current.routeSelection = selection
      await ensureRoutes(latest.current.selectedRegion, indexesOf(selection))
      if (token === selectionToken.current) bumpMotion('route')
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bumpMotion, ensureRoutes],
  )

  /** "실제 경로 불러오기" 버튼: 추정값만 있던 참여자의 경로를 지금 조회하고 지도에 그린다. */
  const loadRoute = useCallback(
    async (participantIndex: number) => {
      const token = ++selectionToken.current
      await ensureRoutes(latest.current.selectedRegion, [participantIndex], true)
      if (token === selectionToken.current) bumpMotion('route')
    },
    [bumpMotion, ensureRoutes],
  )

  /** 타임라인의 구간 클릭: 지도에서 그 구간만 강조하고 그 구간으로 이동. 같은 구간을 다시 누르면 해제. */
  const focusSegment = useCallback(
    (participant: number, segment: number | null) => {
      setSegmentFocus(segment === null ? null : { participant, segment })
      bumpMotion('segment')
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

  async function logout() {
    await apiLogout().catch(() => undefined)
    setAuth({ loaded: true, nickname: null })
  }

  function removeParticipant(key: number) {
    setParticipants((list) => (list.length <= MIN_PARTICIPANTS ? list : list.filter((p) => p.key !== key)))
    setErrors({})
  }

  async function submit() {
    const found = validateParticipants(participants)
    setErrors(found)
    const meetingProblem = !meetingTime
      ? '약속 시간을 입력해 주세요.'
      : !isMeetingFarEnough(meetingTime)
        ? '약속 시간은 지금부터 30분 이상 뒤여야 해요.'
        : null
    setMeetingError(meetingProblem)
    if (Object.keys(found).length > 0 || meetingProblem) {
      setSubmitError('입력하지 않은 항목이 있어요. 붉게 표시된 칸을 확인해 주세요.')
      return
    }
    setSubmitError(null)
    await search(participants, purpose, meetingTime)
  }

  /** 검증을 통과한 입력으로 추천을 받아 결과 화면을 만든다 (직접 입력과 공유 링크가 함께 쓴다). */
  async function search(input: FormParticipant[], purposeValue: Purpose, meeting: string) {
    setLoading(true)
    try {
      const result = await recommend(toRequest(input, purposeValue, toMeetingIso(meeting)))
      setSubmitted({ participants: input, purpose: purposeValue, meetingTime: meeting })
      resetRoutes() // 참여자·지역·약속 시간이 바뀌었을 수 있으니 이전 경로는 버린다
      setData(result)
      setSelectedRegion(0)
      setSelectedPlaceId(null)
      setRouteSelection(0) // 1위 지역의 첫 참여자 경로를 기본으로 펼친다
      setSegmentFocus(null)
      setViewMode('overview')
      latest.current = { ...latest.current, data: result, selectedRegion: 0, routeSelection: 0 }
      bumpMotion('search') // 전체를 보여준 뒤 1·2·3위 마커가 순서대로 떨어진다
      const token = ++selectionToken.current
      void ensureRoutes(0, [0]).then(() => {
        if (token === selectionToken.current) setTimeout(() => token === selectionToken.current && setAutoRoute((n) => n + 1), 1800)
      })
      setUsageTick((t) => t + 1)
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : '추천을 가져오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  // 첫 로드: 로그인 상태 확인 + 공유 링크(?s=)로 들어왔으면 같은 입력으로 결과를 다시 보여준다.
  const booted = useRef(false)
  useEffect(() => {
    if (booted.current) return
    booted.current = true
    const params = new URLSearchParams(window.location.search)
    const shared = parseShareParam(params.get(SHARE_PARAM))
    const err = params.get('login_error')
    if (params.has('login') || err || params.has(SHARE_PARAM)) window.history.replaceState(null, '', window.location.pathname)
    if (err) setLoginError(err === 'denied' ? '카카오 로그인을 취소했어요.' : '카카오 로그인에 실패했어요. 잠시 후 다시 시도해 주세요.')
    fetchMe()
      .then((me) => {
        setAuth({ loaded: true, nickname: me.loggedIn ? me.nickname : null })
        if (me.loggedIn) setStage('app')
      })
      .catch(() => setAuth({ loaded: true, nickname: null }))
    if (shared) {
      setStage('app')
      setPurpose(shared.purpose)
      setParticipants(shared.participants)
      nextKey.current = shared.participants.length + 1
      const stillFuture = isMeetingFarEnough(shared.meetingTime)
      if (!stillFuture) setNotice('공유된 약속 시간이 지나서 기본 약속 시간(다음 토요일 18시)으로 다시 계산했어요.')
      const meeting = stillFuture ? shared.meetingTime : defaultMeetingTime()
      setMeetingTime(meeting)
      void search(shared.participants, shared.purpose, meeting)
    } else if (err) {
      setStage('landing')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const share = useMemo(
    () => (data && submitted ? { text: buildShareText(data), url: buildShareUrl(submitted), loggedIn: auth.nickname !== null } : null),
    [data, submitted, auth.nickname],
  )

  return (
    <div className="app">
      <section className="map-area" aria-label="지도">
        <MapView
          origins={origins}
          regions={regions}
          selectedRegion={selectedRegion}
          selectedPlaceId={selectedPlaceId}
          routeSelection={routeSelection}
          routes={routes}
          segmentFocus={segmentFocus}
          viewMode={viewMode}
          motion={motion}
          autoRouteTick={autoRoute}
          obstacleRef={panelRef}
          onSelectRegion={selectRegion}
          onSelectPlace={selectPlace}
          onToggleView={toggleView}
          onRouteDrawStart={onRouteDrawStart}
        />
      </section>

      <aside className="panel" ref={panelRef}>
        {stage === 'landing' ? (
          <Landing onBrowse={() => setStage('app')} error={loginError} />
        ) : (
          <>
            <AuthBar nickname={auth.nickname} onLogout={logout} />
            {notice && <p className="route-hint notice">{notice}</p>}
        {data && share ? (
          <ResultPanel
            data={data}
            selectedRegion={selectedRegion}
            selectedPlaceId={selectedPlaceId}
            routeSelection={routeSelection}
            routes={routes}
            origins={originInfos}
            plays={plays}
            segmentFocus={segmentFocus}
            onSelectRegion={selectRegion}
            onSelectPlace={selectPlace}
            onSelectRoute={selectRoute}
            onFocusSegment={focusSegment}
            onLoadRoute={loadRoute}
            share={share}
            liveMode={liveMode}
            onToggleLive={() => setLiveMode((v) => !v)}
            onBack={() => {
              setLiveMode(false)
              selectionToken.current++
              setData(null)
              setSelectedPlaceId(null)
              setRouteSelection(null)
              setSegmentFocus(null)
              setViewMode('overview')
              bumpMotion('origins')
            }}
          />
        ) : (
          <InputForm
            participants={participants}
            purpose={purpose}
            meetingTime={meetingTime}
            meetingError={meetingError}
            errors={errors}
            loading={loading}
            submitError={submitError}
            onChangeParticipant={changeParticipant}
            onAdd={addParticipant}
            onRemove={removeParticipant}
            onPurpose={setPurpose}
            onMeetingTime={(value) => {
              setMeetingTime(value)
              setMeetingError(null)
            }}
            onSubmit={submit}
          />
        )}
          </>
        )}
      </aside>

      {introPlaying && <Intro onDone={() => setIntroPlaying(false)} />}

      {showDebug && <DevUsage refreshKey={usageTick} accuracy={data?.meta.estimate_accuracy ?? null} />}
    </div>
  )
}

export default App
