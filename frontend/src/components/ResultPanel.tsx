import { PARTICIPANT_COLORS, PURPOSE_OPTIONS } from '../constants'
import type { RouteSelection, SegmentFocus } from '../map/types'
import { routeKey, type RouteEntries, type RouteEntry } from '../routes'
import type { ParticipantTravel, Place, RecommendResponse, Region, Route } from '../types'
import { kakaoPlaceUrl } from '../links'
import { legColor } from '../map/geometry'
import { lineLabel } from '../routeFormat'
import RouteTimeline, { LineBadge, type TimelinePlay } from './RouteTimeline'
import ShareBar from './ShareBar'

interface Props {
  data: RecommendResponse
  selectedRegion: number
  selectedPlaceId: string | null
  routeSelection: RouteSelection
  routes: RouteEntries
  /** 참여자 순서대로의 출발지 이름·주소 (타임라인의 출발지 줄) */
  origins: { name: string; address: string }[]
  /** 지도에서 경로 그리기가 시작된 시점 (타임라인 등장 모션을 맞춘다). 키는 routeKey */
  plays: Record<string, TimelinePlay>
  segmentFocus: SegmentFocus | null
  onSelectRegion: (index: number) => void
  onSelectPlace: (id: string | null) => void
  onSelectRoute: (selection: RouteSelection) => void
  onFocusSegment: (participant: number, segment: number | null) => void
  /** "실제 경로 불러오기" 버튼 */
  onLoadRoute: (participant: number) => void
  onBack: () => void
  /** "지금 출발"로 켠 실시간 모드 */
  liveMode: boolean
  onToggleLive: () => void
  /** 공유 메시지 본문·다시 보기 주소·로그인 여부 */
  share: { text: string; url: string; loggedIn: boolean }
}

const fmt = (n: number) => Math.round(n).toString()

/** "음식점 > 한식 > 육류,고기" → "한식 · 육류,고기" */
function shortCategory(category: string): string {
  const parts = category.split(' > ').slice(1)
  return (parts.length ? parts : [category]).slice(0, 2).join(' · ')
}

/** 추정 경로(지하철 그래프)를 구간별 배지로 간단히 보여준다. 시각이 없어서 타임라인 대신 쓴다. */
function EstimateFlow({ route, color }: { route: Route; color: string }) {
  return (
    <ol className="tl-flow" aria-label="추정 경로 구간">
      {route.segments.map((seg, i) => (
        <li key={i}>
          {seg.mode === 'WALK' ? (
            <span className="flow-walk"><span aria-hidden="true">🚶</span><small>{Math.max(1, Math.round(seg.minutes))}분</small></span>
          ) : (
            <LineBadge seg={seg} fallbackColor={color} />
          )}
        </li>
      ))}
    </ol>
  )
}

/** 네이버·구글 지도처럼 구간 시간 비율로 쪼갠 막대. 도보=회색, 지하철=호선 색, 버스=종류별 색. 추정은 점선 + "추정". */
function SegmentBar({ route, widthPct }: { route: Route; widthPct: number }) {
  const estimated = route.source === 'estimate'
  const total = route.segments.reduce((a, s) => a + Math.max(s.minutes, 0.5), 0)
  return (
    <span className={`seg-bar${estimated ? ' estimated' : ''}`} style={{ width: `${widthPct}%` }} role="img"
      aria-label={route.segments.map((s) => `${s.mode === 'WALK' ? '도보' : lineLabel(s)} ${Math.max(1, Math.round(s.minutes))}분`).join(', ')}>
      {route.segments.map((s, i) => {
        const share = Math.max(s.minutes, 0.5) / total
        const mins = `${Math.max(1, Math.round(s.minutes))}분`
        const name = s.mode === 'WALK' ? '도보' : lineLabel(s)
        const label = share >= 0.2 ? `${name} ${mins}` : share >= 0.09 ? mins : ''
        const walk = s.mode === 'WALK'
        return (
          <span key={i} className={`seg-part ${walk ? 'walk' : ''}`} title={`${name} ${mins}`}
            style={{ flexGrow: Math.max(s.minutes, 0.5), background: walk ? 'var(--walk-gray)' : legColor(s, '#888'), color: walk ? '#333' : (s.lineTextColor ?? '#fff') }}>
            {label}
          </span>
        )
      })}
      {estimated && <em className="seg-est">추정</em>}
    </span>
  )
}

interface DetailProps {
  entry: RouteEntry | undefined
  travel: ParticipantTravel
  index: number
  color: string
  origin: { name: string; address: string }
  destinationName: string
  meetingTime: string
  play: TimelinePlay | undefined
  segmentFocus: SegmentFocus | null
  onFocusSegment: (participant: number, segment: number | null) => void
  onLoadRoute: (participant: number) => void
  liveMode: boolean
}

/** 참여자 행을 펼쳤을 때의 내용: 안내(추정) / 불러오는 중 / 오류 / 타임라인 */
function RouteDetail({ entry, travel, index, color, origin, destinationName, meetingTime, play, segmentFocus, onFocusSegment, onLoadRoute, liveMode }: DetailProps) {
  const loadButton = (label: string) => (
    <button type="button" className="btn ghost load-route" onClick={() => onLoadRoute(index)}>{label}</button>
  )
  if (!entry) {
    if (!travel.is_estimated) return null // 곧 자동으로 불러온다
    // 1단계 추정값만 있는 참여자: 실제 경로를 아직 조회하지 않았다.
    return (
      <div className="route-summary guidance">
        <p className="route-note">실제 경로 조회 전</p>
        <p className="route-hint">지하철 기준 추정 약 {fmt(travel.estimate_minutes ?? travel.minutes)}분이에요. 실제 경로는 환승·버스·시각표에 따라 달라질 수 있어요.</p>
        {loadButton('실제 경로 불러오기')}
      </div>
    )
  }
  if (entry.status === 'loading') {
    return (
      <div className="route-summary">
        <p className="route-loading"><span className="spinner small" /> 경로를 불러오는 중…</p>
      </div>
    )
  }
  if (entry.status === 'error') {
    return (
      <div className="route-summary guidance">
        <p className="route-note">경로를 불러오지 못했어요</p>
        <p className="route-hint">{entry.message}</p>
        {loadButton('실제 경로 다시 불러오기')}
      </div>
    )
  }
  if (entry.route.source === 'estimate') {
    // 실제 경로 조회에 실패해 추정 경로로 대체된 경우: 시각을 모르니 타임라인 대신 안내만 한다.
    return (
      <div className="route-summary guidance">
        <p className="route-note">실제 경로를 불러오지 못했어요 · 지하철 기준 추정 약 {entry.route.totalMinutes}분</p>
        {entry.note && <p className="route-hint">{entry.note}</p>}
        <EstimateFlow route={entry.route} color={color} />
        {loadButton('실제 경로 다시 불러오기')}
      </div>
    )
  }
  return (
    <div className="route-summary timeline-summary">
      <RouteTimeline
        route={entry.route}
        color={color}
        originName={origin.name}
        originAddress={origin.address}
        destinationName={destinationName}
        meetingTime={meetingTime}
        focusedSegment={segmentFocus?.participant === index ? segmentFocus.segment : null}
        onFocusSegment={(segment) => onFocusSegment(index, segment)}
        play={play ?? null}
        liveManual={liveMode}
      />
    </div>
  )
}

function TravelBars({
  region,
  maxMinutes,
  routeSelection,
  routes,
  origins,
  meetingTime,
  plays,
  segmentFocus,
  onSelectRoute,
  onFocusSegment,
  onLoadRoute,
  liveMode,
}: {
  region: Region
  maxMinutes: number
  routeSelection: RouteSelection
  routes: RouteEntries
  origins: { name: string; address: string }[]
  meetingTime: string
  plays: Record<string, TimelinePlay>
  segmentFocus: SegmentFocus | null
  onSelectRoute: (selection: RouteSelection) => void
  onFocusSegment: (participant: number, segment: number | null) => void
  onLoadRoute: (participant: number) => void
  liveMode: boolean
}) {
  return (
    <>
      <div className="travel-head">
        <h3>참여자별 이동시간</h3>
        <button
          type="button"
          className="btn ghost"
          aria-pressed={routeSelection === 'all'}
          onClick={() => onSelectRoute(routeSelection === 'all' ? null : 'all')}
        >
          {routeSelection === 'all' ? '경로 숨기기' : '모두 보기'}
        </button>
      </div>
      <ul className="bars" aria-label="참여자별 이동시간">
        {region.participants.map((p, i) => {
          const open = routeSelection === 'all' || routeSelection === i
          return (
            <li key={`${p.name}-${i}`} className={open ? 'open' : ''}>
              <button
                type="button"
                className={`bar-row${open ? ' selected' : ''}`}
                aria-expanded={open}
                aria-label={`${p.name} 이동 경로 ${open ? '숨기기' : '보기'}`}
                onClick={() => onSelectRoute(routeSelection === i ? null : i)}
              >
                <span className="bar-name">
                  <i className="dot" style={{ background: PARTICIPANT_COLORS[i] }} />
                  {p.name}
                </span>
                <span className="bar-track">
                  {(() => {
                    const e = routes[routeKey(region.station.id, i)]
                    const widthPct = (p.minutes / maxMinutes) * 100
                    return e?.status === 'ok' && e.route.source !== 'estimate' ? (
                      <SegmentBar route={e.route} widthPct={widthPct} />
                    ) : (
                      <span
                        className={`bar-fill${p.is_estimated ? ' estimated' : ''}`}
                        style={{ width: `${widthPct}%`, background: PARTICIPANT_COLORS[i] }}
                      >
                        {p.is_estimated && <em className="seg-est">추정</em>}
                      </span>
                    )
                  })()}
                </span>
                <span className="bar-value">
                  {fmt(p.minutes)}분{p.is_estimated && <em className="badge">추정</em>}
                </span>
                <span className="route-cta" aria-hidden="true">{open ? '경로 닫기 ▴' : '경로 보기 ›'}</span>
              </button>
              <div className="route-detail" aria-hidden={!open}>
                <div className="route-detail-inner">
                  <RouteDetail
                    entry={open ? routes[routeKey(region.station.id, i)] : undefined}
                    travel={p}
                    index={i}
                    color={PARTICIPANT_COLORS[i]}
                    origin={origins[i] ?? { name: p.name, address: '' }}
                    destinationName={region.station.name}
                    meetingTime={meetingTime}
                    play={plays[routeKey(region.station.id, i)]}
                    segmentFocus={segmentFocus}
                    onFocusSegment={onFocusSegment}
                    onLoadRoute={onLoadRoute}
                    liveMode={liveMode}
                  />
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </>
  )
}

function PlaceCard({ place, selected, onSelect }: { place: Place; selected: boolean; onSelect: () => void }) {
  return (
    <li className={`place-card${selected ? ' selected' : ''}`}>
      <button type="button" className="place-main" onClick={onSelect} aria-pressed={selected}>
        <span className="place-rank">{place.rank}</span>
        <span className="place-body">
          <strong>{place.name}</strong>
          <span className="place-sub">
            {shortCategory(place.category)} · 역에서 {fmt(place.distance_m)}m
          </span>
          <span className="place-rating">
            {place.rating != null ? (
              <>
                ★ {place.rating.toFixed(1)} <small>(리뷰 {place.review_count?.toLocaleString()}개)</small>
              </>
            ) : (
              <small>평점 정보 없음</small>
            )}
          </span>
          <span className="place-reason">{place.reason}</span>
        </span>
        <span className="place-score" title="PlaceScore">
          {place.score.toFixed(2)}
          <small>PlaceScore</small>
        </span>
      </button>
      <a className="place-link" href={kakaoPlaceUrl(place)} target="_blank" rel="noopener">
        카카오맵에서 보기 ↗
      </a>
    </li>
  )
}

export default function ResultPanel({
  data,
  selectedRegion,
  selectedPlaceId,
  routeSelection,
  routes,
  origins,
  plays,
  segmentFocus,
  onSelectRegion,
  onSelectPlace,
  onSelectRoute,
  onFocusSegment,
  onLoadRoute,
  onBack,
  share,
  liveMode,
  onToggleLive,
}: Props) {
  const region = data.regions[selectedRegion]
  const maxMinutes = Math.max(...data.regions.flatMap((r) => r.participants.map((p) => p.minutes)))
  const purposeLabel = PURPOSE_OPTIONS.find((o) => o.value === data.meta.purpose)?.label ?? ''
  const hasEstimate = data.regions.some((r) => r.participants.some((p) => p.is_estimated))
  const { phase2, travel_source: travelSource } = data.meta
  const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length
  const estimateAvg = avg(region.participants.map((p) => p.estimate_minutes ?? p.minutes))
  const gain = estimateAvg - avg(region.participants.map((p) => p.minutes))
  // 1단계(그래프 추정, 버스 없음) 순위와 달라졌다면 실제 경로가 순위를 바꾼 것이다.
  const rankChange =
    travelSource !== 'estimate' && region.stage1_rank !== region.rank
      ? `추정 ${region.stage1_rank}위 → 실제 경로 반영 ${region.rank}위` +
        (gain >= 3 ? ` · 추정보다 평균 ${Math.round(gain)}분 빠름 (버스 등 지하철 외 경로 가능성)` : '')
      : null

  return (
    <div className="result">
      <header className="result-head">
        <button type="button" className="btn ghost" onClick={onBack}>
          ← 조건 다시 입력
        </button>
        <span className="chip">
          {purposeLabel} · {region.participants.length}명 · 대중교통
        </span>
      </header>

      <div className="live-bar">
        <button type="button" className={`btn ${liveMode ? 'live-on' : 'ghost'}`} aria-pressed={liveMode} onClick={onToggleLive}>
          {liveMode ? '● 실시간 끄기' : '지금 출발'}
        </button>
        <span className="live-hint">
          {liveMode
            ? '지금 기준 다음 열차·버스를 30초마다 갱신해요 (경로를 펼치면 승차역 옆에 표시)'
            : '누르면 승차역의 실시간 도착 정보를 보여줘요. 출발 30분 전부터는 자동으로 켜져요.'}
        </span>
      </div>

      <ShareBar text={share.text} url={share.url} loggedIn={share.loggedIn} />

      <div className="tabs" role="tablist" aria-label="추천 지역">
        {data.regions.map((r, i) => (
          <button
            key={r.station.id}
            type="button"
            role="tab"
            aria-selected={i === selectedRegion}
            className={i === selectedRegion ? 'active' : ''}
            onClick={() => onSelectRegion(i)}
          >
            <span className="tab-rank">{r.rank}위</span>
            <span className="tab-name">{r.station.name}</span>
          </button>
        ))}
      </div>

      <section className="region" role="tabpanel" aria-label={`${region.rank}위 ${region.station.name}`}>
        <div className="region-title">
          <h2>{region.station.name}</h2>
          <span className="score" title="RegionScore (높을수록 좋음)">
            RegionScore <b>{region.score.toFixed(3)}</b>
          </span>
        </div>
        {region.station.lines.length > 0 && <p className="lines">{region.station.lines.join(' · ')}</p>}
        <p className={`source-line${travelSource === 'estimate' ? ' estimate' : ''}`}>
          {travelSource === 'estimate'
            ? '이동시간: 지하철 그래프 추정값'
            : `이동시간: ${travelSource === 'google' ? 'Google' : 'ODsay'} 실제 경로 기준 (후보 ${phase2.candidates}곳 중 최종 ${data.regions.length}곳)`}
        </p>
        {rankChange && <p className="rank-change">{rankChange}</p>}
        <p className="reason">{region.reason}</p>

        <TravelBars
          region={region}
          maxMinutes={maxMinutes}
          routeSelection={routeSelection}
          routes={routes}
          origins={origins}
          meetingTime={data.meta.meeting_time}
          plays={plays}
          segmentFocus={segmentFocus}
          onSelectRoute={onSelectRoute}
          onFocusSegment={onFocusSegment}
          onLoadRoute={onLoadRoute}
          liveMode={liveMode}
        />

        <dl className="metrics">
          <div>
            <dt>평균</dt>
            <dd>{region.metrics.avg_minutes.toFixed(1)}분</dd>
          </div>
          <div>
            <dt>최대</dt>
            <dd>{region.metrics.max_minutes.toFixed(1)}분</dd>
          </div>
          <div>
            <dt>편차</dt>
            <dd>{region.metrics.std_minutes.toFixed(1)}분</dd>
          </div>
        </dl>
      </section>

      <section className="places">
        <h3>이 지역 추천 장소 {region.places.length > 0 && `Top ${region.places.length}`}</h3>
        {region.places.length === 0 ? (
          <p className="empty">조건에 맞는 장소를 찾지 못했어요.</p>
        ) : (
          <ul>
            {region.places.map((p) => (
              <PlaceCard
                key={p.id}
                place={p}
                selected={p.id === selectedPlaceId}
                onSelect={() => onSelectPlace(p.id === selectedPlaceId ? null : p.id)}
              />
            ))}
          </ul>
        )}
      </section>

      <footer className="notes">
        {data.meta.age_preference.is_assumed && (
          <p>※ 연령대별 장소 선호도는 실제 데이터가 아닌 임의로 정한 설정값이에요.</p>
        )}
        {hasEstimate && (
          <p>
            ※ '추정'은 실제 경로 확인에 실패해 지하철 그래프로 계산한 이동시간이에요
            {phase2.reason ? ` (${phase2.reason})` : ''}.
          </p>
        )}
        {data.meta.place_warnings.map((w) => (
          <p key={w}>※ {w}</p>
        ))}
      </footer>
    </div>
  )
}
