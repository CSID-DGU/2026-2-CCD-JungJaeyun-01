// 인트로를 지금 재생할지 결정한다: 세션당 1번, prefers-reduced-motion이면 생략, 로그인 복귀·공유 링크 접속이면 생략.
const KEY = 'meetpick-intro-seen'

export function shouldPlayIntro(): boolean {
  try {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
    const params = new URLSearchParams(window.location.search)
    if (params.has('s') || params.has('login') || params.has('login_error')) return false
  } catch {
    return false
  }
  try {
    return sessionStorage.getItem(KEY) !== '1'
  } catch {
    return true // 저장소를 못 쓰면 기억할 수 없으니 그냥 재생한다
  }
}

export function markIntroSeen(): void {
  try {
    sessionStorage.setItem(KEY, '1')
  } catch {
    // 저장소를 쓸 수 없어도 화면에는 영향이 없다.
  }
}
