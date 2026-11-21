import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento, o painel fala com o gateway via proxy (sem CORS).
// MODELMESH_API aponta para o gateway, por exemplo http://127.0.0.1:8000.
const target = process.env.MODELMESH_API || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/admin": target,
      "/health": target,
      "/metrics": target,
      "/v1": target,
    },
  },
});
