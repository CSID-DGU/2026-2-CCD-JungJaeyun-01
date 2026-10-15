/** 발자국 하나 (인트로와 로딩 화면이 함께 쓴다) */
export default function Foot({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 34" width={size} height={size * 1.36} aria-hidden="true">
      <ellipse cx="12" cy="11" rx="6.5" ry="9.5" fill="currentColor" />
      <ellipse cx="12" cy="27" rx="5" ry="5.5" fill="currentColor" />
    </svg>
  )
}
