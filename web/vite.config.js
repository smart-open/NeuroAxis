import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // Front/back separation: dev requests proxy to the FastAPI backend.
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
