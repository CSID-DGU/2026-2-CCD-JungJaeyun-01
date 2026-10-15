import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 루트의 .env 하나를 백엔드와 공유한다.
  envDir: '..',
  // 프론트에 노출되는 키는 카카오맵 JavaScript 키(VITE_KAKAO_JS_KEY)뿐이다. 다른 키를 추가하지 말 것.
  envPrefix: ['VITE_KAKAO_JS_'],
  server: {
    port: 5173,
    // cloudflared 임시 터널(https://xxxx.trycloudflare.com)로 들어오는 요청을 허용한다.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      // /api/* 는 경로를 바꾸지 않고 그대로 백엔드로 전달한다.
      // 외부 접속(터널 등)도 5173 하나로 끝난다. Host를 그대로 넘겨야(changeOrigin: false) 백엔드가 접속 주소를 알 수 있다.
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
      // 카카오 로그인 리다이렉트도 같은 출처로 받아 세션 쿠키가 프론트와 같은 출처에 저장되게 한다.
      '/auth': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
})
