import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// In dev, the FastAPI server runs on :8000; proxy /api so the app uses
// same-origin URLs in both dev and the built deployment.
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
