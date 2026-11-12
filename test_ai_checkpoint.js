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
    const context = await browser.newContext({ viewport:{ width:390, height:780 } });
    const requests = [];
    const discarded = [];
    const checkpointId = 'checkpoint12345678901234567890';
    let alwaysCheckpoint = false;
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://127.0.0.1:8766') return route.abort();
      if (url.pathname === '/api/ask') {
        const body = JSON.parse(route.request().postData());
        requests.push(body);
        const stream = body.checkpoint_id && !alwaysCheckpoint
          ? 'event: text\ndata: {"delta":"最终回答已完成"}\n\nevent: done\ndata: {"model":"mock"}\n\n'
          : 'event: tool\ndata: {"id":"tool-1","name":"查看目录","status":"done"}\n\n' +
            'event: checkpoint\ndata: {"id":"' + checkpointId + '","rounds":5}\n\n' +
            'event: done\ndata: {"model":"mock","paused":true,"note":"已保存进度，可点击继续任务"}\n\n';
        return route.fulfill({ status:200, contentType:'text/event-stream', body:stream });
      }
      if (url.pathname === '/api/checkpoint/discard') {
        discarded.push(JSON.parse(route.request().postData()).id);
        return route.fulfill({ status:200, contentType:'application/json', body:'{"discarded":true}' });
      }
      if (url.pathname === '/api/health') return route.fulfill({ status:200, contentType:'application/json', body:'{"ok":false}' });
      if (url.pathname === '/' || url.pathname === '/intern_summaries.js' || url.pathname === '/resume_template.js') {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({ status:200, contentType:name.endsWith('.js') ? 'text/javascript' : 'text/html', body:fs.readFileSync(path.join(__dirname, name)) });
      }
      return route.fulfill({ status:404, body:'' });
    });
    await context.addInitScript(() => {
      localStorage.setItem('whq-recent-work-2026-10-27-v1', '1');
      localStorage.setItem('whq-personal-ai-auto-continue-v1', '0');
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('http://127.0.0.1:8766/', { waitUntil:'domcontentloaded' });
    await page.evaluate(() => show('ai'));
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_project"]').check();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('五轮任务');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'paused');
    assert.equal(requests.length, 1);
    assert.equal(await page.locator('#ai-chat [data-resume]').count(), 1);
    await page.reload({ waitUntil:'domcontentloaded' });
    await page.evaluate(() => show('ai'));
    assert.equal(requests.length, 1);
    assert.equal(await page.locator('#ai-chat [data-resume]').count(), 1);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask .local-access-picker label:has(input[name="local_project"])').click();
    await page.locator('#ai-chat [data-resume]').click();
    assert.equal(requests.length, 1);
    assert.match(await page.locator('#ai-status').textContent(), /恢复.*权限/);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_project"]').check();
    await page.locator('#ai-chat [data-resume]').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'done');
    assert.equal(requests.length, 2);
    assert.equal(requests[1].checkpoint_id, checkpointId);
    assert.equal(requests[1].local_access.project, true);
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /最终回答已完成/);
    assert.equal(await page.locator('#ai-chat [data-resume]').count(), 0);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('放弃任务');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'paused');
    await page.locator('#ai-chat [data-discard]').click();
    await page.waitForFunction(() => aiRuns.at(-1).checkpointId === '');
    assert.deepEqual(discarded, [checkpointId]);
    await page.reload({ waitUntil:'domcontentloaded' });
    assert.equal(await page.locator('#ai-chat [data-resume]').count(), 0);
    await page.locator('#ai-auto-continue').check();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('自动续做任务');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1)?.state === 'done');
    assert.equal(requests.length, 5);
    assert.equal(requests[4].checkpoint_id, checkpointId);
    assert.equal(await page.locator('#ai-chat [data-resume]').count(), 0);
    alwaysCheckpoint = true;
    await page.locator('#ai-ask textarea[name="prompt"]').fill('需要多段的任务');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1)?.state === 'paused' && aiRuns.at(-1)?.autoSegments === 3);
    assert.equal(requests.length, 8);
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /连续推进已到上限/);
    assert.deepEqual(errors, []);
    await context.close();
    console.log('Agent checkpoint browser flow passed.');
  } finally { await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
