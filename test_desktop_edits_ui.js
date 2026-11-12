const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({ executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless:true });
  try {
    for (const viewport of [{width:1280,height:800}, {width:390,height:780}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      const calls = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/*', (route) => {
        const url = new URL(route.request().url());
        const asset = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        if (['index.html', 'intern_summaries.js', 'resume_template.js'].includes(asset)) {
          return route.fulfill({status:200, contentType:asset.endsWith('.js') ? 'text/javascript' : 'text/html', body:fs.readFileSync(path.join(__dirname, asset))});
        }
        if (url.pathname === '/api/health') return route.fulfill({status:200, contentType:'application/json', body:'{"ok":false}'});
        if (url.pathname === '/api/desktop-edits') return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({files:['C:\\Users\\test\\Desktop\\notes.txt'],history:calls.some((item) => item.action === 'commit') ? [{id:'abc',path:'C:\\Users\\test\\Desktop\\notes.txt',status:calls.some((item) => item.action === 'undo') ? 'undone' : 'applied',at:'now'}] : []})});
        if (url.pathname.startsWith('/api/desktop-edits/')) {
          const action = url.pathname.split('/').at(-1);
          calls.push({action, body:JSON.parse(route.request().postData())});
          const data = action === 'inspect' ? {kind:'text',content:'before'} : ['preview','draft'].includes(action) ? {stage_id:'stage',path:'C:\\Users\\test\\Desktop\\notes.txt',kind:'text',diff:'-before\n+after',old_text:'before',new_text:'after'} : {id:'abc',status:action === 'undo' ? 'undone' : 'applied'};
          return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(data)});
        }
        return route.fulfill({status:404, body:''});
      });
      await page.goto('http://127.0.0.1:8767/', {waitUntil:'domcontentloaded'});
      await page.evaluate(() => show('ai'));
      await page.locator('#desktop-edit-open').click();
      await page.locator('#desktop-edit-path').fill('C:\\Users\\test\\Desktop\\notes.txt');
      await page.locator('#desktop-edit-inspect').click();
      await page.waitForFunction(() => document.getElementById('desktop-edit-source').textContent === 'before');
      assert.equal(await page.locator('#desktop-edit-source').textContent(), 'before');
      await page.locator('#desktop-edit-old').fill('before');
      await page.locator('#desktop-edit-new').fill('after');
      await page.locator('#desktop-edit-preview-button').click();
      await page.waitForFunction(() => !document.getElementById('desktop-edit-commit').disabled);
      assert.match(await page.locator('#desktop-edit-diff').textContent(), /\+after/);
      assert.equal(calls.some((item) => item.action === 'commit'), false);
      await page.locator('#desktop-edit-new').fill('later');
      assert.equal(await page.locator('#desktop-edit-commit').isDisabled(), true);
      await page.locator('#desktop-edit-preview-button').click();
      await page.waitForFunction(() => !document.getElementById('desktop-edit-commit').disabled);
      await page.locator('#desktop-edit-commit').click();
      await page.waitForFunction(() => !!document.querySelector('#desktop-edit-history button'));
      assert.equal(calls.filter((item) => item.action === 'commit').length, 1);
      await page.locator('#desktop-edit-history button').click();
      assert.equal(calls.filter((item) => item.action === 'undo').length, 1);
      await page.locator('#desktop-edit-instruction').fill('请精简');
      await page.locator('#desktop-edit-draft').click();
      await page.waitForFunction(() => !document.getElementById('desktop-edit-commit').disabled);
      assert.equal(calls.at(-1).body.allow_model, true);
      assert.equal(await page.locator('#desktop-edit-new').inputValue(), 'after');
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('desktop edit UI OK');
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
