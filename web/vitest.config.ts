import { defineConfig } from "vitest/config";

// The acceptance gate's (tools/verify_pack.py) two engine suites:
// tests/baseline.test.ts, which holds a pack's stated baseline to what doing
// nothing costs, and tests/optimal.test.ts, which replays the certified line.
export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
