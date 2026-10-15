import { BRAND } from '../brand'

/** 지도 핀 안에 발자국이 들어간 로고 마크 */
export function PinMark({ size = 40, className = '' }: { size?: number; className?: string }) {
  return (
    <svg className={`pin-mark ${className}`} width={size} height={size * 1.25} viewBox="0 0 48 60" aria-hidden="true">
      <path d="M24 2C12.4 2 3 11.2 3 22.6 3 38 24 58 24 58s21-20 21-35.4C45 11.2 35.6 2 24 2z" fill="var(--brand)" />
      <ellipse cx="24" cy="20" rx="6.4" ry="9" fill="#fff" />
      <ellipse cx="24" cy="33" rx="4.8" ry="5.4" fill="#fff" />
    </svg>
  )
}

/** 로고 마크 + MEET PICK 워드마크 */
export default function Logo({ size = 'md', showKo = true }: { size?: 'sm' | 'md' | 'lg'; showKo?: boolean }) {
  const px = size === 'lg' ? 56 : size === 'md' ? 34 : 24
  return (
    <span className={`logo logo-${size}`} aria-label={`${BRAND.name} ${BRAND.nameKo}`}>
      <PinMark size={px * 0.8} />
      <span className="logo-text">
        <span className="logo-word">MEET <b>PICK</b></span>
        {showKo && <span className="logo-ko">{BRAND.nameKo}</span>}
      </span>
    </span>
  )
}
