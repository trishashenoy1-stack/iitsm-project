import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Used once VITE_USE_MOCK=false and P2's FastAPI server is running.
    proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" },
  },
});
