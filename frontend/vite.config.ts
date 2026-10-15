import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxy = process.env.API_PROXY || "http://127.0.0.1:8000";
const collabProxy = process.env.COLLAB_PROXY || "http://127.0.0.1:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api/v1/collaboration": {
        target: collabProxy,
        ws: true,
      },
      "/api": {
        target: apiProxy,
      },
    },
  },
});
