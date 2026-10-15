interface Props {
  onBrowse: () => void
  /** 로그인 실패 안내 (콜백에서 돌아온 경우) */
  error: string | null
}

/** 첫 화면: 카카오 로그인 또는 로그인 없이 둘러보기 (추천 기능은 둘 다 똑같이 쓸 수 있다) */
export default function Landing({ onBrowse, error }: Props) {
  return (
    <div className="landing">
      <h1>맞춤형 모임 장소 추천</h1>
      <p className="landing-sub">참여자들의 출발지를 입력하면 모두에게 공평한 모임 지역과 장소를 추천해 드려요.</p>
      {error && <p className="field-error" role="alert">{error}</p>}
      {/* 인가 코드 방식은 페이지 이동이 필요하므로 버튼이 아니라 링크로 연결한다 */}
      <a className="btn kakao landing-login" href="/auth/kakao/login">카카오로 시작하기</a>
      <button type="button" className="landing-browse" onClick={onBrowse}>로그인 없이 둘러보기</button>
      <p className="landing-note">로그인하면 결과를 카카오톡 "나에게 보내기"로 받을 수 있어요. 추천 기능은 로그인 없이도 모두 쓸 수 있어요.</p>
    </div>
  )
}
