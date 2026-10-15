// 카카오톡 공유 (Kakao JavaScript SDK의 Kakao.Share.sendDefault). 친구·채팅방은 카톡 공유 창에서 고른다.
// 지도와 같은 JavaScript 키(VITE_KAKAO_JS_KEY)를 쓰며, 카카오 콘솔에 웹 도메인이 등록돼 있어야 한다.

/* eslint-disable @typescript-eslint/no-explicit-any */
const SDK_URL = 'https://t1.kakaocdn.net/kakao_js_sdk/2.7.4/kakao.min.js'

let loading: Promise<any> | null = null

function loadSdk(): Promise<any> {
  const w = window as any
  if (w.Kakao) return Promise.resolve(w.Kakao)
  if (loading) return loading
  loading = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SDK_URL
    script.onload = () => resolve(w.Kakao)
    script.onerror = () => {
      loading = null
      reject(new Error('카카오 공유 SDK를 불러오지 못했어요. 네트워크 연결을 확인해 주세요.'))
    }
    document.head.appendChild(script)
  })
  return loading
}

export async function shareToKakaoTalk(text: string, url: string): Promise<void> {
  const key = import.meta.env.VITE_KAKAO_JS_KEY
  if (!key) throw new Error('VITE_KAKAO_JS_KEY가 .env에 없어서 카카오톡 공유를 쓸 수 없어요.')
  const Kakao = await loadSdk()
  if (!Kakao.isInitialized()) Kakao.init(key)
  Kakao.Share.sendDefault({
    objectType: 'text',
    text,
    link: { mobileWebUrl: url, webUrl: url },
    buttonTitle: '결과 다시 보기',
  })
}
