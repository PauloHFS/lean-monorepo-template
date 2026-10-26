import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Em dev, o front roda em :5173 e a API em :8000. Vite proxia /api -> API.
// Em produção, o front é buildado para /apps/web/dist e servido pelo próprio
// FastAPI em / (mesmo host), então não precisa de proxy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Sem sourcemap no build: a API serve dist/assets publicamente, então o
    // .map entregaria o código-fonte TypeScript completo.
    sourcemap: false,
    target: 'es2022',
  },
})
