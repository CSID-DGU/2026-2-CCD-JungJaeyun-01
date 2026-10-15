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
    proxy: {
      // /api/* 는 경로를 바꾸지 않고 그대로 백엔드로 전달한다.
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      // 카카오 로그인 리다이렉트도 5173으로 받아 세션 쿠키가 프론트와 같은 출처에 저장되게 한다.
      '/auth': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
})
