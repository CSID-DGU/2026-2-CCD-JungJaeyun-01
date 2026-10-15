import { Check } from 'lucide-react'

const STEPS = ['참여자', '모임 조건', '추천']

/** 입력 화면 상단 단계 표시: 참여자 → 모임 조건 → 추천. current는 1~3, 그 앞 단계는 완료 표시 */
export default function Stepper({ current }: { current: 1 | 2 | 3 }) {
  return (
    <ol className="stepper" aria-label="진행 단계">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n < current ? 'done' : n === current ? 'current' : 'todo'
        return (
          <li key={label} className={`step ${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="step-dot">{state === 'done' ? <Check size={14} strokeWidth={3} aria-hidden="true" /> : n}</span>
            <span className="step-label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}
