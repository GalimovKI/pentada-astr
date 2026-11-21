import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The public base path contains no secrets. API_PROXY_TARGET stays server-side.
const base = process.env.APP_BASE_PATH || "/";
export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      [`${base}api`]: {
        target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000",
        rewrite: (path) => "/" + path.slice(base.length),
      },
    },
  },
});
