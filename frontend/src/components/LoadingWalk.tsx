import { useEffect, useState } from 'react'
import Foot from './Foot'

const MESSAGES = ['이동시간 계산 중…', '장소 고르는 중…']

/** 추천 계산 중 화면: 인트로의 발자국 모션을 반복하고 안내 문구를 바꿔 보여준다. */
export default function LoadingWalk() {
  const [step, setStep] = useState(0)
  useEffect(() => {
    const t = setTimeout(() => setStep(1), 2400)
    return () => clearTimeout(t)
  }, [])
  return (
    <div className="loading-walk" role="status" aria-live="polite">
      <div className="walk-trail" aria-hidden="true">
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={`walk-foot ${i % 2 ? 'right' : 'left'}`} style={{ ['--i' as string]: i }}>
            <Foot size={20} />
          </span>
        ))}
      </div>
      <p key={step} className="loading-msg">{MESSAGES[step]}</p>
      <small>모두에게 공평한 곳을 찾고 있어요</small>
    </div>
  )
}
