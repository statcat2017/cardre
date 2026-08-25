import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Coverage measurement and threshold enforcement are opt-in via the
// TEST_COVERAGE_THRESHOLDS env flag. This lets focused/targeted runs
// (`npm test`, `npx vitest run <subset>`) succeed without failing on global
// thresholds computed over unrun files. CI and `npm run test:coverage` set
// the flag to enforce the full-suite 60/60/60/50 gate while preserving
// reporters and full-suite measurement.
const enforceCoverage = process.env.TEST_COVERAGE_THRESHOLDS === "1";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      enabled: enforceCoverage,
      reporter: ["text", "json", "html"],
      all: true,
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.{test,spec}.{ts,tsx}",
        "src/**/__tests__/**",
        "src/test/**",
        "src/main.tsx",
        "src/api/schema.d.ts",
        "src/api/errorCodes.ts",
      ],
      thresholds: enforceCoverage
        ? {
            lines: 60,
            statements: 60,
            functions: 60,
            branches: 50,
          }
        : undefined,
    },
  },
});
