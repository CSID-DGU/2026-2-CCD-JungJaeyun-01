interface Props {
  nickname: string | null
  onLogout: () => void
}

/** 패널 맨 위 헤더: 로그인 상태면 닉네임과 로그아웃, 아니면 로그인 링크 */
export default function AuthBar({ nickname, onLogout }: Props) {
  return (
    <div className="auth-bar">
      <span className="auth-brand">모임 장소 추천</span>
      {nickname ? (
        <span className="auth-user">
          <strong>{nickname}</strong>님
          <button type="button" className="btn ghost small" onClick={onLogout}>로그아웃</button>
        </span>
      ) : (
        <a className="btn ghost small" href="/auth/kakao/login">카카오 로그인</a>
      )}
    </div>
  )
}
