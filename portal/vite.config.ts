import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import path from "path"

export default defineConfig({
  base: process.env.VITE_BASE_PATH || "/portal/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/news": { target: "http://localhost:46401", changeOrigin: true },
      "/admin": { target: "http://localhost:46401", changeOrigin: true },
      "/auth": { target: "http://localhost:46401", changeOrigin: true },
      "/health": { target: "http://localhost:46401", changeOrigin: true },
    },
  },
})
