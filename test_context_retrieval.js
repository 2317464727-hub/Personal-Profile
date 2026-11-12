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
    const context = await browser.newContext();
    const requests = [];
    const fileSearches = [];
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/ask') {
        requests.push(JSON.parse(route.request().postData()));
        return route.fulfill({ status:200, contentType:'text/event-stream', body:'event: text\ndata: {"delta":"已核查"}\n\nevent: done\ndata: {"model":"mock"}\n\n' });
      }
      if (url.pathname === '/api/context/files') {
        fileSearches.push(JSON.parse(route.request().postData()));
        return route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify({sources:[{source:'D:\\work\\inventory-note.md', excerpt:'库存风险诊断：补货仍为模拟。'}]}) });
      }
      if (url.pathname === '/api/health') return route.fulfill({ status:200, contentType:'application/json', body:'{"ok":true,"model":"mock"}' });
      if (url.pathname === '/' || url.pathname === '/intern_summaries.js' || url.pathname === '/resume_template.js') {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({ status:200, contentType:name.endsWith('.js') ? 'text/javascript' : 'text/html', body:fs.readFileSync(path.join(__dirname, name)) });
      }
      return route.fulfill({ status:404, body:'' });
    });
    await context.addInitScript(() => {
      if (localStorage.getItem('retrieval-test-init')) return;
      localStorage.setItem('retrieval-test-init', '1');
      localStorage.setItem('whq-recent-work-2026-10-27-v1', '1');
      localStorage.setItem('whq-personal-resume-v1', JSON.stringify({name:'PRIVATE_RESUME_NAME', experience:'PRIVATE_RESUME_BODY'}));
      const recent = Array.from({length:20}, (_, i) => ({id:'recent-' + i, date:'2026-10-28', time:'10:00', end:'11:00', workspace:'video', title:'视频整理 ' + i, body:'制作脚本'}));
      recent.push({id:'old-inventory', date:'2026-09-01', time:'10:00', end:'11:00', workspace:'inventory', title:'库存风险诊断', body:'只读核查高库存；补货仍为模拟。'});
      localStorage.setItem('whq-personal-logs-v1', JSON.stringify(recent));
    });
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8766/', {waitUntil:'domcontentloaded'});
    await page.evaluate(() => show('ai'));
    async function ask(prompt) {
      await page.locator('#ai-ask textarea[name="prompt"]').fill(prompt);
      await page.locator('#ai-ask .send-btn').click();
      await page.waitForFunction(() => aiRuns.at(-1).state === 'done');
      return requests.at(-1);
    }
    let request = await ask('库存风险诊断');
    assert.equal(request.records_context, '');
    assert.equal(request.file_context, '');
    assert.equal(fileSearches.length, 0);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_records"]').check();
    request = await ask('库存风险诊断');
    assert.match(request.records_context, /\[周历:old-inventory\].*补货仍为模拟/);
    assert.doesNotMatch(request.records_context, /recent-19/);
    assert.doesNotMatch(JSON.stringify(request), /PRIVATE_RESUME_BODY/);
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /周历：2026-09-01 库存风险诊断/);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_records"]').uncheck();
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_files"]').check();
    request = await ask('库存风险诊断');
    assert.equal(request.records_context, '');
    assert.match(request.file_context, /inventory-note\.md.*补货仍为模拟/s);
    assert.equal(fileSearches.at(-1).scope, 'files');
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /文件：.*inventory-note\.md/);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_files"]').uncheck();
    request = await ask('库存风险诊断');
    assert.equal(request.file_context, '');
    assert.equal(fileSearches.length, 1);
    const priorCalls = requests.length;
    await page.locator('#ai-ask textarea[name="prompt"]').fill('第一份简历里有没有 PRIVATE_RESUME_BODY');
    await page.locator('#ai-ask .send-btn').click();
    assert.equal(requests.length, priorCalls);
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /\[简历:实习与工作经历\].*PRIVATE_RESUME_BODY/s);
    await browser.close();
    console.log('Question-matched records, scoped files and source labels: OK');
  } finally { if (browser.isConnected()) await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
