import { defineConfig } from "vitest/config";

// Tests live next to the modules they cover, in `*.test.js[x]` files.
// `node` environment is fine for the lib-level tests we have today
// (pure async functions hitting a mocked fetch); switch to `jsdom`
// later if/when component-level tests land.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.{js,jsx}"],
    globals: true,
  },
});
