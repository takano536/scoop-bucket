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
  for (let attempt = 0; attempt < 2; attempt++) {
    const app = await electron.launch({ executablePath, env, timeout: 60000 });
    try {
      const page = await app.firstWindow({ timeout: 60000 });
      await page.waitForFunction(() => document.body.innerText.trim().length > 20, { timeout: 60000 });
      assert.equal(await app.evaluate(({ app }) => app.isPackaged), true);
      assert.equal(await app.evaluate(({ app }) => app.getPath('userData')), env.HERMES_DESKTOP_USER_DATA_DIR);
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
  console.log('Native packaged Light launch/relaunch and user-data retention passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
