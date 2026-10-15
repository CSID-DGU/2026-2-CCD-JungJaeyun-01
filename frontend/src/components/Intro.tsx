import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { BRAND } from '../brand'
import { markIntroSeen } from '../introState'
import { PinMark } from './Logo'

const TOTAL_MS = 2600
const WALKERS = 9
const STEPS = 4

interface Print {
  x: number
  y: number
  rot: number
  delay: number
}

/** 화면 가장자리의 여러 곳에서 가운데(핀 위치)로 걸어오는 발자국들 */
function makePrints(w: number, h: number): Print[] {
  const prints: Print[] = []
  const reach = Math.hypot(w, h) / 2
  for (let k = 0; k < WALKERS; k++) {
    const angle = (k / WALKERS) * Math.PI * 2 + 0.35
    const sx = Math.cos(angle) * reach * 0.95
    const sy = Math.sin(angle) * reach * 0.95
    const rot = (Math.atan2(-sy, -sx) * 180) / Math.PI + 90 // 가운데를 향한 방향
    const nx = -Math.sin(angle)
    const ny = Math.cos(angle)
    for (let i = 0; i < STEPS; i++) {
      const t = (i + 1) / (STEPS + 0.6) // 가운데 직전까지
      const side = i % 2 === 0 ? 1 : -1 // 왼발·오른발 번갈아
      prints.push({
        x: sx * (1 - t) + nx * side * 9,
        y: sy * (1 - t) + ny * side * 9,
        rot,
        delay: 0.05 + k * 0.04 + i * 0.2,
      })
    }
  }
  return prints
}

function Foot() {
  return (
    <svg viewBox="0 0 24 34" width="22" height="30" aria-hidden="true">
      <ellipse cx="12" cy="11" rx="6.5" ry="9.5" fill="currentColor" />
      <ellipse cx="12" cy="27" rx="5" ry="5.5" fill="currentColor" />
    </svg>
  )
}

/**
 * 첫 접속 인트로(약 2.5초): 발자국이 걸어와 핀으로 모이고 → 핀이 톡 튀며 로고 → 슬로건.
 * CSS/SVG 애니메이션만 쓴다. 건너뛰기를 누르거나 끝나면 onDone.
 */
export default function Intro({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false)
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  })
  const prints = useMemo(() => makePrints(window.innerWidth, window.innerHeight), [])

  useEffect(() => {
    markIntroSeen()
    const fade = setTimeout(() => setLeaving(true), TOTAL_MS)
    const end = setTimeout(() => done.current(), TOTAL_MS + 350)
    return () => {
      clearTimeout(fade)
      clearTimeout(end)
    }
  }, [])

  const skip = () => {
    setLeaving(true)
    setTimeout(() => done.current(), 150)
  }

  return (
    <div className={`intro${leaving ? ' leaving' : ''}`} role="presentation">
      <div className="intro-stage">
        <div className="intro-prints" aria-hidden="true">
          {prints.map((p, i) => (
            <span
              key={i}
              className="intro-print"
              style={{ ['--x' as string]: `${p.x}px`, ['--y' as string]: `${p.y}px`, ['--rot' as string]: `${p.rot}deg`, ['--d' as string]: `${p.delay}s` } as CSSProperties}
            >
              <Foot />
            </span>
          ))}
        </div>
        <div className="intro-pin"><PinMark size={64} /></div>
        <div className="intro-logo">
          <span className="intro-word">MEET <b>PICK</b></span>
          <span className="intro-ko">{BRAND.nameKo}</span>
        </div>
        <p className="intro-slogan">{BRAND.slogan}</p>
      </div>
      <button type="button" className="intro-skip" onClick={skip}>건너뛰기</button>
    </div>
  )
}
