import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api and /files to the FastAPI backend on :8000,
// so the frontend can use relative URLs in both dev and prod.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Allow tunnel/preview hosts (Vercel, localhost tunnels, etc.) in dev.
    allowedHosts: true,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/files": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
