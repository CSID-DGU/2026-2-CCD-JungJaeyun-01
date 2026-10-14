import { PARTICIPANT_COLORS, PURPOSE_OPTIONS } from '../constants'
import type { RouteSelection } from '../map/types'
import { routeKey, type RouteEntries, type RouteEntry } from '../routes'
import type { Place, RecommendResponse, Region, RouteSegment } from '../types'

interface Props {
  data: RecommendResponse
  selectedRegion: number
  selectedPlaceId: string | null
  routeSelection: RouteSelection
  routes: RouteEntries
  onSelectRegion: (index: number) => void
  onSelectPlace: (id: string | null) => void
  onSelectRoute: (selection: RouteSelection) => void
  onBack: () => void
}

const fmt = (n: number) => Math.round(n).toString()

/** "음식점 > 한식 > 육류,고기" → "한식 · 육류,고기" */
function shortCategory(category: string): string {
  const parts = category.split(' > ').slice(1)
  return (parts.length ? parts : [category]).slice(0, 2).join(' · ')
}

/** 버스 노선명: 숫자·영문 번호는 "472번"처럼, 이미 이름이 있으면 그대로 */
const busName = (name: string) => (/^[0-9A-Za-z-]+$/.test(name) ? `${name}번` : name)

/** "도보 5분" / "2호선 합정→을지로3가 16분" / "🚌 472번 A→B 12분" (0.x분 구간도 최소 1분으로 보여준다) */
function segmentText(seg: RouteSegment): string {
  const minutes = Math.max(1, Math.round(seg.minutes))
  if (seg.mode === 'WALK') return `도보 ${minutes}분`
  const name = seg.lineName ? (seg.mode === 'BUS' ? busName(seg.lineName) : seg.lineName) : seg.mode === 'BUS' ? '버스' : '지하철'
  const span = seg.from && seg.to ? ` ${seg.from}→${seg.to}` : ''
  return `${seg.mode === 'BUS' ? '🚌 ' : ''}${name}${span} ${minutes}분`
}

function RouteSummary({ entry, color }: { entry: RouteEntry | undefined; color: string }) {
  if (!entry) return null // 아직 요청 전 (닫힌 행)
  if (entry.status === 'loading') {
    return (
      <div className="route-summary">
        <p className="route-loading">
          <span className="spinner small" /> 경로를 불러오는 중…
        </p>
      </div>
    )
  }
  if (entry.status === 'error') {
    return (
      <div className="route-summary">
        <p className="route-note">경로를 불러오지 못했어요</p>
        <p className="route-hint">{entry.message}</p>
      </div>
    )
  }
  const { route, note } = entry
  const estimated = route.source === 'estimate'
  return (
    <div className="route-summary">
      <p className="route-total">
        총 {route.totalMinutes}분 · 환승 {route.transfers}회
        <em className={`badge${estimated ? '' : ' source'}`}>{estimated ? '추정 경로' : route.source === 'google' ? 'Google 실제 경로' : 'ODsay 경로'}</em>
      </p>
      <ol className="route-legs" aria-label="구간">
        {route.segments.map((seg, i) => (
          <li
            key={i}
            className={`leg ${seg.mode.toLowerCase()}`}
            style={{ borderColor: seg.mode === 'WALK' ? color : (seg.lineColor ?? color) }}
          >
            {segmentText(seg)}
          </li>
        ))}
      </ol>
      {note && <p className="route-hint">{note}</p>}
    </div>
  )
}

function TravelBars({
  region,
  maxMinutes,
  routeSelection,
  routes,
  onSelectRoute,
}: {
  region: Region
  maxMinutes: number
  routeSelection: RouteSelection
  routes: RouteEntries
  onSelectRoute: (selection: RouteSelection) => void
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
                  <span
                    className={`bar-fill${p.is_estimated ? ' estimated' : ''}`}
                    style={{ width: `${(p.minutes / maxMinutes) * 100}%`, background: PARTICIPANT_COLORS[i] }}
                  />
                </span>
                <span className="bar-value">
                  {fmt(p.minutes)}분{p.is_estimated && <em className="badge">추정</em>}
                </span>
              </button>
              <div className="route-detail" aria-hidden={!open}>
                <div className="route-detail-inner">
                  <RouteSummary entry={open ? routes[routeKey(region.station.id, i)] : undefined} color={PARTICIPANT_COLORS[i]} />
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
      {/^https?:\/\//.test(place.url) && (
        <a className="place-link" href={place.url} target="_blank" rel="noopener noreferrer">
          카카오맵에서 보기 ↗
        </a>
      )}
    </li>
  )
}

export default function ResultPanel({
  data,
  selectedRegion,
  selectedPlaceId,
  routeSelection,
  routes,
  onSelectRegion,
  onSelectPlace,
  onSelectRoute,
  onBack,
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
          onSelectRoute={onSelectRoute}
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
