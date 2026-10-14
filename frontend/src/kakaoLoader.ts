// 카카오맵 JavaScript SDK를 한 번만 불러온다.
// 프론트에서 쓰는 유일한 외부 API 키(VITE_KAKAO_JS_KEY)이며, 카카오 개발자 콘솔에 웹 도메인 등록이 필요하다.

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    kakao: any
  }
}

let loading: Promise<any> | null = null

export function loadKakaoMaps(appKey: string): Promise<any> {
  if (loading) return loading
  loading = new Promise((resolve, reject) => {
    if (!appKey) {
      reject(new Error('VITE_KAKAO_JS_KEY가 .env에 없습니다. 루트 .env에 키를 넣고 개발 서버를 다시 시작해 주세요.'))
      return
    }
    const script = document.createElement('script')
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(appKey)}&autoload=false&libraries=services`
    script.onload = () => window.kakao.maps.load(() => resolve(window.kakao))
    script.onerror = () => {
      loading = null
      reject(
        new Error(
          '카카오맵을 불러오지 못했습니다. JavaScript 키와 카카오 개발자 콘솔의 웹 도메인(http://localhost:5173) 등록을 확인해 주세요.',
        ),
      )
    }
    document.head.appendChild(script)
  })
  return loading
}
