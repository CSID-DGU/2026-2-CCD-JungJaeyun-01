import { Scale, Share2, Utensils } from 'lucide-react'
import { BRAND } from '../brand'
import Logo from './Logo'

interface Props {
  onBrowse: () => void
  /** 로그인 실패 안내 (콜백에서 돌아온 경우) */
  error: string | null
}

const FEATURES = [
  { Icon: Scale, title: '이동시간 공정성', text: '모두의 이동시간이 비슷한 지역을 찾아요' },
  { Icon: Utensils, title: '목적 맞춤 장소', text: '식사·카페·술, 모임에 맞는 장소를 골라줘요' },
  { Icon: Share2, title: '카톡 공유', text: '결과를 카카오톡으로 바로 공유해요' },
]

/** 카카오 말풍선 심볼 (카카오 로그인 디자인 가이드: 검은 말풍선) */
function KakaoSymbol() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#000"
        d="M12 3C6.48 3 2 6.58 2 11c0 2.86 1.86 5.37 4.66 6.78l-1.1 4.03c-.1.36.3.65.62.44l4.78-3.18c.34.03.68.05 1.04.05 5.52 0 10-3.58 10-8S17.52 3 12 3z"
      />
    </svg>
  )
}

/** 첫 화면: 로고·슬로건·한 줄 설명, 카카오 로그인(가장 크게), 로그인 없이 둘러보기, 기능 소개 카드 3개 */
export default function Landing({ onBrowse, error }: Props) {
  return (
    <div className="landing-screen">
      <div className="landing-inner">
        <header className="landing-hero">
          <Logo size="lg" />
          <h1 className="landing-slogan">{BRAND.slogan}</h1>
          <p className="landing-tagline">{BRAND.tagline}</p>
        </header>

        <div className="landing-actions">
          {error && <p className="field-error" role="alert">{error}</p>}
          {/* 인가 코드 방식은 페이지 이동이 필요하므로 버튼이 아니라 링크로 연결한다 */}
          <a className="kakao-login" href="/auth/kakao/login">
            <KakaoSymbol />
            <span>카카오 로그인</span>
          </a>
          <button type="button" className="landing-browse" onClick={onBrowse}>로그인 없이 둘러보기</button>
        </div>

        <ul className="feature-cards" aria-label="주요 기능">
          {FEATURES.map(({ Icon, title, text }) => (
            <li key={title} className="feature-card">
              <span className="feature-icon"><Icon size={22} strokeWidth={2.2} aria-hidden="true" /></span>
              <span className="feature-body">
                <strong>{title}</strong>
                <span>{text}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="landing-note">로그인하면 결과를 카카오톡 "나에게 보내기"로 받을 수 있어요. 추천 기능은 로그인 없이도 모두 쓸 수 있어요.</p>
      </div>
    </div>
  )
}
