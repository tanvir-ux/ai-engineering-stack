/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "./",
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
