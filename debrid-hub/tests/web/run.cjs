#!/usr/bin/env node
// Runs every *.test.cjs in this directory sequentially (jsdom windows and
// their globals aren't isolated well enough to safely run in parallel in one
// process) and prints an aggregate summary. Exit code is non-zero if any
// suite failed -- CI-friendly.
const fs = require('fs');
const path = require('path');

const dir = __dirname;
const files = fs.readdirSync(dir).filter(f => f.endsWith('.test.cjs')).sort();

(async () => {
  const summaries = [];
  for (const file of files) {
    const mod = require(path.join(dir, file));
    try {
      summaries.push(await mod.run());
    } catch (e) {
      console.error(`\n=== ${file} ===\n  ✗ threw: ${e.stack || e}`);
      summaries.push({ name: file, ok: false, total: 1, failed: 1 });
    }
  }

  const totalTests = summaries.reduce((a, s) => a + s.total, 0);
  const totalFailed = summaries.reduce((a, s) => a + s.failed, 0);
  const allOk = summaries.every(s => s.ok);

  console.log(`\n${'='.repeat(50)}`);
  console.log(`${files.length} suite(s), ${totalTests} assertion(s), ${totalFailed} failed`);
  console.log(allOk ? 'ALL WEB TESTS PASSED' : 'SOME WEB TESTS FAILED');
  process.exit(allOk ? 0 : 1);
})();
