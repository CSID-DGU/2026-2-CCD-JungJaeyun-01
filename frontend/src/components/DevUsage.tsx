import { useEffect, useState } from 'react'
import { fetchUsage, type UsageInfo } from '../api'
import type { EstimateAccuracy } from '../types'

interface Props {
  /** 값이 바뀔 때마다 오늘 호출 수를 다시 불러온다 (추천·경로 요청 직후) */
  refreshKey: number
  accuracy: EstimateAccuracy | null
}

/** 개발용 표시: 오늘 경로 API 호출 수. 개발 서버(npm run dev)에서만 보인다. */
export default function DevUsage({ refreshKey, accuracy }: Props) {
  const [usage, setUsage] = useState<UsageInfo | null>(null)

  useEffect(() => {
    if (!import.meta.env.DEV) return
    let cancelled = false
    fetchUsage()
      .then((u) => !cancelled && setUsage(u))
      .catch(() => !cancelled && setUsage(null))
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  if (!import.meta.env.DEV || !usage) return null
  const c = usage.counters
  return (
    <aside className="dev-usage" aria-label="개발용 경로 API 호출 수">
      <strong>
        {usage.provider} · {usage.mode}
      </strong>
      <span>
        오늘 matrix {c.matrix ?? 0} · route {c.route ?? 0} · 캐시 {c.cache_hit ?? 0}
        {usage.mode === 'replay' && ` · 저장본 ${c.replay_hit ?? 0}/${c.replay_miss ?? 0}없음`} · 오류 {c.error ?? 0}
      </span>
      {accuracy && (
        <span>
          추정 오차 평균 {accuracy.mae_minutes}분 (편향 {accuracy.bias_minutes > 0 ? '+' : ''}
          {accuracy.bias_minutes}분)
        </span>
      )}
    </aside>
  )
}
