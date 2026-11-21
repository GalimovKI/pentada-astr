import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Only this server-side setting controls the proxy. No .env or DB settings
// are loaded into the browser; the client always uses relative /api URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000",
      },
    },
  },
});
