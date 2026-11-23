import { useEffect, useState } from 'react'
import type { FormParticipant } from '../validate'

export default function CarRow({person, stationId}: {person: FormParticipant; stationId: string}) {
  const [summary, setSummary] = useState('조회 중…')
  const [fare, setFare] = useState<number | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const response = await fetch('/api/drive', {
          method: 'POST', signal: controller.signal, headers: {'Content-Type':'application/json'},
          body: JSON.stringify({lat: person.origin?.lat, lng: person.origin?.lng, station_id: stationId}),
        })
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || '자동차 경로 조회 실패')
        setSummary(data.minutes + '분')
        setFare(data.taxi)
      } catch (error) {
        if (!controller.signal.aborted) setSummary(error instanceof Error ? error.message : '조회 실패')
      }
    }
    void load()
    return () => controller.abort()
  }, [person.origin, stationId])
  return <li><details><summary>{person.name} · 자동차 · {summary}</summary>
    <p>현재 교통 기준 · {person.origin?.name} 출발</p>
    {fare != null && <p>카카오 예상 택시비 {fare.toLocaleString()}원</p>}
  </details></li>
}
