import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Tailwind v4 is wired as a Vite plugin (no postcss.config / tailwind.config
// needed). react() enables JSX + Fast Refresh (HMR).
export default defineConfig({
  plugins: [react(), tailwindcss()],
});
