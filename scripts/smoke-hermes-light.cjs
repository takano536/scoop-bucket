'use strict';
const { createRequire } = require('node:module');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const assert = require('node:assert/strict');
const [source, executablePath, output] = process.argv.slice(2);
const upstreamRequire = createRequire(path.join(source, 'apps/desktop/package.json'));
const { _electron: electron } = upstreamRequire('playwright');

(async () => {
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-light-smoke-'));
  const env = { ...process.env,
    HERMES_HOME: path.join(scratch, 'home'),
    HERMES_DESKTOP_USER_DATA_DIR: path.join(scratch, 'user-data'),
  };
  delete env.ELECTRON_RUN_AS_NODE;
  // The app must launch without borrowing Python/Node/Git from the build runner.
  // This checks initial native launch only, not remote gateway feature coverage.
  for (const key of Object.keys(env)) {
    if (key.toLowerCase() === 'path') delete env[key];
  }
  env.PATH = [path.dirname(executablePath), path.join(env.SystemRoot, 'System32'), env.SystemRoot].join(path.delimiter);
  const checks = { runtimePath: 'application directory and Windows system directories only', launches: [] };
  for (let attempt = 0; attempt < 2; attempt++) {
    const app = await electron.launch({ executablePath, env, timeout: 60000 });
    try {
      const page = await app.firstWindow({ timeout: 60000 });
      await page.waitForFunction(() => document.body.innerText.trim().length > 20, { timeout: 60000 });
      assert.equal(await app.evaluate(({ app }) => app.isPackaged), true);
      assert.equal(await app.evaluate(({ app }) => app.getPath('userData')), env.HERMES_DESKTOP_USER_DATA_DIR);
      const status = await page.evaluate(() => window.hermesDesktop.updates.check({ force: true }));
      assert.equal(status.mechanism, 'external');
      assert.equal(status.supported, false);
      const apply = await page.evaluate(() => window.hermesDesktop.updates.apply());
      assert.equal(apply.mechanism, 'external');
      // Commit previews reject apply; stable external builds return manual-only.
      assert.ok(apply.ok === false || apply.manual === true);
      checks.launches.push({ updaterCheck: status, updaterApply: apply });
      if (attempt === 0) {
        await page.evaluate(() => localStorage.setItem('scoop-smoke-marker', 'retained'));
        await page.screenshot({ path: path.join(output, 'smoke.png') });
      } else {
        assert.equal(await page.evaluate(() => localStorage.getItem('scoop-smoke-marker')), 'retained');
      }
    } finally {
      await app.close();
    }
  }
  fs.writeFileSync(path.join(output, 'native-checks.json'), JSON.stringify(checks, null, 2) + '\n');
  console.log('Native Light launch/relaunch, restricted PATH, external updater IPC and user-data retention passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
