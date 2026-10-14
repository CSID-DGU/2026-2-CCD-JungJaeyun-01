import { PARTICIPANT_COLORS, PURPOSE_OPTIONS } from '../constants'
import type { Place, RecommendResponse, Region } from '../types'

interface Props {
  data: RecommendResponse
  selectedRegion: number
  selectedPlaceId: string | null
  onSelectRegion: (index: number) => void
  onSelectPlace: (id: string | null) => void
  onBack: () => void
}

const fmt = (n: number) => Math.round(n).toString()

/** "음식점 > 한식 > 육류,고기" → "한식 · 육류,고기" */
function shortCategory(category: string): string {
  const parts = category.split(' > ').slice(1)
  return (parts.length ? parts : [category]).slice(0, 2).join(' · ')
}

function TravelBars({ region, maxMinutes }: { region: Region; maxMinutes: number }) {
  return (
    <ul className="bars" aria-label="참여자별 이동시간">
      {region.participants.map((p, i) => (
        <li key={`${p.name}-${i}`}>
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
        </li>
      ))}
    </ul>
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

export default function ResultPanel({ data, selectedRegion, selectedPlaceId, onSelectRegion, onSelectPlace, onBack }: Props) {
  const region = data.regions[selectedRegion]
  const maxMinutes = Math.max(...data.regions.flatMap((r) => r.participants.map((p) => p.minutes)))
  const purposeLabel = PURPOSE_OPTIONS.find((o) => o.value === data.meta.purpose)?.label ?? ''
  const hasEstimate = data.regions.some((r) => r.participants.some((p) => p.is_estimated))

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
        <p className="reason">{region.reason}</p>

        <TravelBars region={region} maxMinutes={maxMinutes} />

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
          <p>※ '추정'은 대중교통 경로 조회에 실패해 직선거리로 계산한 이동시간이에요.</p>
        )}
        {data.meta.place_warnings.map((w) => (
          <p key={w}>※ {w}</p>
        ))}
      </footer>
    </div>
  )
}
