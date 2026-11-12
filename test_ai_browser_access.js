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
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://127.0.0.1:8766') return route.abort();
      if (url.pathname === '/api/ask') {
        const request = JSON.parse(route.request().postData());
        requests.push(request);
        if (request.messages.at(-1)?.content === '项目操作测试') {
          const body = 'event: change\ndata: {"path":"personal/demo.py","diff":"-before\\n+after","created":false}\n\n' +
            'event: check\ndata: {"name":"personal_python","passed":true,"output":"OK"}\n\n' +
            'event: text\ndata: {"delta":"修改和测试完成"}\n\nevent: done\ndata: {"model":"mock"}\n\n';
          return route.fulfill({ status:200, contentType:'text/event-stream', body });
        }
        return route.fulfill({ status:200, contentType:'text/event-stream', body:'event: text\ndata: {"delta":"收到"}\n\nevent: done\ndata: {"model":"mock"}\n\n' });
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
      if (localStorage.getItem('whq-personal-ai-runs-v1') === null) {
        localStorage.setItem('whq-personal-ai-runs-v1', JSON.stringify([{ id:'prior', prompt:'PrivateLocalMarker', text:'旧答复', state:'done' }]));
      }
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('http://127.0.0.1:8766/', { waitUntil:'domcontentloaded' });
    await page.evaluate(() => show('ai'));
    await page.evaluate(() => {
      localStorage.setItem('whq-personal-logs-v1', JSON.stringify([{ id:'privacy-test', date:'2026-10-28', time:'09:00', end:'10:00', workspace:'personal', title:'PrivateRecordMarker', body:'PrivateRecordBody' }]));
      document.getElementById('ai-note').value = 'PrivateEditorMarker';
    });

    async function ask(prompt) {
      await page.locator('#ai-ask textarea[name="prompt"]').fill(prompt);
      await page.locator('#ai-ask .send-btn').click();
      await page.waitForFunction(() => aiRuns.at(-1).state === 'done');
      return requests.at(-1);
    }

    const ordinary = await ask('普通问答');
    assert.equal(ordinary.browser_access, 'none');
    assert.equal(ordinary.browser_url, '');
    assert.deepEqual(ordinary.local_access, { records:false, editor:false, files:false, project:false });
    assert.equal(JSON.stringify(ordinary).includes('PrivateRecordMarker'), false);
    assert.equal(JSON.stringify(ordinary).includes('PrivateEditorMarker'), false);
    assert.equal(JSON.stringify(ordinary).includes('PrivateLocalMarker'), false);
    await page.locator('#ai-prompts button').first().click();
    assert.equal(requests.length, 1);
    assert.match(await page.locator('#ai-ask textarea[name="prompt"]').inputValue(), /实习/);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('');
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_records"]').check();
    assert.match(await page.locator('#local-access-menu summary').textContent(), /周历记录/);
    const records = await ask('RecordsPromptPrivate');
    assert.equal(records.local_access.records, true);
    assert.match(records.records_context, /PrivateRecordBody/);
    assert.equal(records.editor_context, '');
    assert.equal(await page.locator('#ai-ask input[name="local_records"]').isChecked(), true);
    const afterRecords = await ask('新的普通问答');
    assert.equal(afterRecords.local_access.records, true);
    assert.equal(JSON.stringify(afterRecords).includes('PrivateRecordBody'), true);
    assert.equal(JSON.stringify(afterRecords).includes('RecordsPromptPrivate'), true);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask .local-access-picker label:has(input[name="local_records"])').click();
    const afterClose = await ask('关闭记录权限后的问答');
    assert.equal(afterClose.local_access.records, false);
    assert.equal(JSON.stringify(afterClose).includes('PrivateRecordBody'), false);
    assert.equal(JSON.stringify(afterClose).includes('RecordsPromptPrivate'), false);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_editor"]').check();
    const editor = await ask('编辑区问题');
    assert.equal(editor.records_context, '');
    assert.match(editor.editor_context, /PrivateEditorMarker/);
    assert.equal(await page.locator('#ai-ask input[name="local_editor"]').isChecked(), true);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask .local-access-picker label:has(input[name="local_editor"])').click();
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_files"]').check();
    const files = await ask('查看桌面');
    assert.equal(files.local_access.files, true);
    assert.equal(files.records_context, '');
    assert.equal(files.editor_context, '');
    assert.equal(JSON.stringify(files).includes('PrivateRecordBody'), false);
    assert.equal(await page.locator('#ai-ask input[name="local_files"]').isChecked(), true);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask .local-access-picker label:has(input[name="local_files"])').click();
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_project"]').check();
    assert.match(await page.locator('#local-access-menu summary').textContent(), /项目操作/);
    const project = await ask('项目操作测试');
    assert.equal(project.local_access.project, true);
    assert.equal(project.local_access.files, false);
    assert.equal(await page.locator('#ai-chat .run').last().locator('.project-report').count(), 2);
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /测试通过/);
    assert.equal(await page.locator('#ai-ask input[name="local_project"]').isChecked(), true);
    await page.reload({ waitUntil:'domcontentloaded' });
    await page.evaluate(() => show('ai'));
    assert.equal(await page.locator('#ai-ask input[name="local_project"]').isChecked(), true);
    const projectFollowup = await ask('项目操作测试');
    assert.equal(projectFollowup.local_access.project, true);
    assert.match(JSON.stringify(projectFollowup.messages), /修改和测试完成/);
    await page.evaluate(() => { activeSiteUrl = 'https://example.com/'; sitePanel.hidden = false; });
    await page.locator('#browser-access-menu summary').click();
    await page.locator('#ai-ask input[value="read"]').check();
    assert.match(await page.locator('#browser-access-menu summary').textContent(), /读取网页/);
    assert.equal(await page.locator('#ai-ask input[name="local_records"]').isDisabled(), true);
    const read = await ask('打开 https://example.com 并读网页');
    assert.equal(read.browser_access, 'read');
    assert.equal(read.browser_url, 'https://example.com/');
    assert.equal(read.records_context.includes('PrivateLocalMarker'), false);
    assert.equal(read.editor_context.includes('PrivateLocalMarker'), false);
    assert.deepEqual(read.local_access, { records:false, editor:false, files:false, project:false });
    assert.equal(JSON.stringify(read.messages).includes('PrivateLocalMarker'), false);
    assert.equal(await page.locator('#ai-ask input[value="read"]').isChecked(), true);
    await page.locator('#browser-access-menu summary').click();
    await page.locator('#ai-ask input[value="control"]').check();
    const control = await ask('读取页面并点击导航');
    assert.equal(control.browser_access, 'control');
    assert.equal(await page.locator('#ai-ask input[value="control"]').isChecked(), true);
    assert.equal(requests.length, 10);
    await page.reload({ waitUntil:'domcontentloaded' });
    await page.evaluate(() => show('ai'));
    assert.equal(await page.locator('#ai-ask input[value="control"]').isChecked(), true);
    assert.equal(await page.locator('#ai-ask input[name="local_project"]').isChecked(), false);
    await page.locator('#browser-access-menu summary').click();
    await page.locator('#ai-ask input[value="none"]').check();
    await page.evaluate(() => { focusSpace = 'agent'; aiFocus = 'personal'; });
    await ask('帮我看啊我现在在哪个工作区');
    let reply = await page.locator('#ai-chat .run').last().textContent();
    assert.match(reply, /whq agnnt/);
    assert.match(reply, /周历当前筛选：“agent”/);
    assert.match(reply, /AI 历史当前筛选：“个人档案”/);
    assert.match(reply, /不能证明你在 Codex 中选中了哪个工作区/);
    await ask('有哪些工作区');
    reply = await page.locator('#ai-chat .run').last().textContent();
    assert.match(reply, /平台登记的工作区：agent、whq agnnt/);
    await ask('这个里面有什么项目');
    reply = await page.locator('#ai-chat .run').last().textContent();
    assert.match(reply, /本机资料.*本机文件/);
    assert.equal(requests.length, 10);
    const followup = await ask('普通追问');
    assert.equal(JSON.stringify(followup.messages).includes('平台登记的工作区'), false);
    assert.equal(JSON.stringify(followup.messages).includes('这次没有授权读取项目文件'), false);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_files"]').check();
    const listing = await ask('这个里面有什么项目');
    assert.equal(listing.local_access.files, true);
    assert.equal(requests.length, 12);
    assert.equal(await page.locator('#ai-ask input[name="local_files"]').isChecked(), true);
    const second = await context.newPage();
    await second.goto('http://127.0.0.1:8766/', { waitUntil:'domcontentloaded' });
    await second.evaluate(() => show('ai'));
    assert.equal(await second.locator('#ai-ask input[name="local_files"]').isChecked(), true);
    await second.locator('#local-access-menu summary').click();
    await second.locator('#ai-ask .local-access-picker label:has(input[name="local_files"])').click();
    await page.waitForFunction(() => !document.querySelector('#ai-ask input[name="local_files"]').checked);
    assert.equal(await page.locator('#local-access-value').textContent(), '未选择');
    await second.close();
    await page.reload({ waitUntil:'domcontentloaded' });
    assert.equal(await page.locator('#ai-ask input[name="local_files"]').isChecked(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.deepEqual(errors, []);
    console.log('Browser permission request flow passed.');
  } finally { await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
