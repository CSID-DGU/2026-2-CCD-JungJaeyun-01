import { Scale, Sparkles } from 'lucide-react'
import type { Place, RecommendResponse, Region } from '../types'

type Meta = RecommendResponse['meta']

const pct = (v: number) => `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`

/** "이동 공정성 높음/보통/낮음": 숫자보다 먼저 보이는 사람 말 표시 */
export function FairnessBadge({ region }: { region: Region }) {
  const f = region.fairness
  return (
    <span className={`fair-badge ${f.level}`} title={`가장 오래 걸리는 사람과 가장 적게 걸리는 사람의 차이 ${f.gap_minutes.toFixed(0)}분`}>
      <Scale size={14} aria-hidden="true" /> 이동 공정성 {f.label}
    </span>
  )
}

/** RegionScore 계산 근거: 지표별 값, 0~1 정규화, 가중치, 점수에 기여한 몫 */
export function RegionScoreExplain({ region, weights }: { region: Region; weights: Meta['weights'] }) {
  const rows = [
    { label: '평균 이동시간', value: `${region.metrics.avg_minutes.toFixed(1)}분`, n: region.normalized.avg, w: weights.avg },
    { label: '최대 이동시간', value: `${region.metrics.max_minutes.toFixed(1)}분`, n: region.normalized.max, w: weights.max },
    { label: '이동시간 편차', value: `${region.metrics.std_minutes.toFixed(1)}분`, n: region.normalized.std, w: weights.std },
  ]
  return (
    <details className="explain">
      <summary>
        점수는 이렇게 계산돼요 <span className="explain-score">RegionScore {region.score.toFixed(3)}</span>
      </summary>
      <p className="explain-lead">
        평균·최대·편차를 후보 지역들 사이에서 0(가장 좋음)~1(가장 나쁨)로 맞춘 뒤 가중치대로 더해 <b>1에서 빼요</b>. 점수가 1에 가까울수록 모두에게 빠르고 공평한 곳이에요.
      </p>
      <table className="explain-table">
        <thead>
          <tr><th>지표</th><th>값</th><th>좋은 정도</th><th>가중치</th><th>점수 기여</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td>{r.value}</td>
              <td><span className="mini-bar"><i style={{ width: pct(1 - r.n) }} /></span></td>
              <td>{r.w}</td>
              <td>{(r.w * (1 - r.n)).toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={4}>합계 (= RegionScore)</td><td>{region.score.toFixed(3)}</td></tr>
        </tfoot>
      </table>
      <p className="explain-note">가중치는 현재 잠정값이에요. 사용자 설문으로 조정할 예정이고, 가중치를 바꿨을 때 순위 변화는 평가 문서(docs/evaluation)에 있어요.</p>
    </details>
  )
}

const PLACE_LABELS: [keyof Place['components'], string][] = [
  ['accessibility', '역에서의 거리'],
  ['rating', '평점 (리뷰 수 보정)'],
  ['popularity', '리뷰 수(인기)'],
  ['purpose', '모임 목적 적합'],
  ['age', '연령대 적합'],
]

/** PlaceScore 계산 근거 */
export function PlaceScoreExplain({ place }: { place: Place }) {
  return (
    <details className="explain place-explain">
      <summary>
        점수 보기 <span className="explain-score">PlaceScore {place.score.toFixed(2)}</span>
      </summary>
      <p className="explain-lead">
        <Sparkles size={13} aria-hidden="true" /> 다섯 항목(각 0~1점)에 가중치를 곱해 더한 값이에요. 1점에 가까울수록 이 모임에 어울리는 장소예요.
      </p>
      <table className="explain-table">
        <thead>
          <tr><th>항목</th><th>점수</th><th>가중치</th><th>점수 기여</th></tr>
        </thead>
        <tbody>
          {PLACE_LABELS.map(([key, label]) => {
            const v = place.components[key] ?? 0
            const w = place.weights_used[key] ?? 0
            return (
              <tr key={key}>
                <td>{label}{key === 'age' && place.age_fit_assumed ? ' *' : ''}</td>
                <td><span className="mini-bar"><i style={{ width: pct(v) }} /></span> {v.toFixed(2)}</td>
                <td>{w}</td>
                <td>{(v * w).toFixed(3)}</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr><td colSpan={3}>합계 (= PlaceScore)</td><td>{place.score.toFixed(3)}</td></tr>
        </tfoot>
      </table>
      {place.rating == null && (
        <p className="explain-note">평점 정보를 받지 못해, 평점은 전체 평균(사전값)으로 두고 리뷰 수는 0으로 계산했어요. 화면에는 가짜 평점을 보여주지 않아요.</p>
      )}
      {place.age_fit_assumed && <p className="explain-note">* 연령대 적합 점수는 실제 조사 데이터가 아닌 임의로 정한 값이에요.</p>}
    </details>
  )
}

/** 공평 추천과 장소 만족 추천이 갈릴 때의 안내 */
export function PicksBanner({ picks, regions, onSelect }: { picks: Meta['picks']; regions: Region[]; onSelect: (index: number) => void }) {
  const idx = (rank: number) => regions.findIndex((r) => r.rank === rank)
  if (!picks.differs) {
    return <p className="picks-banner same">{picks.summary}</p>
  }
  return (
    <div className="picks-banner">
      <p>{picks.summary}</p>
      <div className="picks-actions">
        <button type="button" className="btn ghost small" onClick={() => onSelect(idx(picks.fair_rank))}>공평한 곳 보기</button>
        <button type="button" className="btn ghost small" onClick={() => onSelect(idx(picks.satisfaction_rank))}>장소 좋은 곳 보기</button>
      </div>
    </div>
  )
}
