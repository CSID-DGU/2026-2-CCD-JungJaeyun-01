import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 루트의 .env 하나를 백엔드와 공유한다.
  envDir: '..',
  // 프론트에 노출되는 키는 카카오맵 JavaScript 키뿐이다. 다른 키를 추가하지 말 것.
  envPrefix: ['KAKAO_JS_'],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
