import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em dev, o front roda em :5173 e a API em :8000. Vite proxia /api -> API.
// Em produção, o front é buildado para /apps/web/dist e servido pelo próprio
// FastAPI em / (mesmo host), então não precisa de proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
        secure: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
  },
});
