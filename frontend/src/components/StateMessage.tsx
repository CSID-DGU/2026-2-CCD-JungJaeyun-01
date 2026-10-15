import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

interface Props {
  Icon: LucideIcon
  title: string
  children?: ReactNode
  tone?: 'empty' | 'error'
  role?: 'alert'
}

/** 빈 상태·에러 화면: 일러스트 느낌의 큰 아이콘 + 친근한 문구 */
export default function StateMessage({ Icon, title, children, tone = 'empty', role }: Props) {
  return (
    <div className={`state-message ${tone}`} role={role}>
      <span className="state-art" aria-hidden="true">
        <i className="state-blob" />
        <Icon size={30} strokeWidth={2} />
      </span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  )
}
