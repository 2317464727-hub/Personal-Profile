const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

let chromium;
try {
  ({ chromium } = require('playwright-core'));
} catch {
  ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core')));
}

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 780 } });
    let requestBody;
    let askRequests = 0;
    await context.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://127.0.0.1:8766') return route.abort();
      if (url.pathname === '/api/ask') {
        askRequests++;
        requestBody = JSON.parse(route.request().postData());
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: text\ndata: {"delta":"收到"}\n\nevent: done\ndata: {"model":"mock"}\n\n' });
      }
      if (url.pathname === '/api/health') return route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":false}' });
      if (url.pathname === '/' || url.pathname === '/intern_summaries.js' || url.pathname === '/resume_template.js') {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({ status: 200, contentType: name.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/html; charset=utf-8', body:fs.readFileSync(path.join(__dirname, name)) });
      }
      return route.fulfill({ status: 404, body:'' });
    });
    await context.addInitScript(() => {
      localStorage.setItem('whq-recent-work-2026-10-27-v1', '1');
      localStorage.setItem('whq-personal-ai-runs-v1', JSON.stringify([
        { id:'old', at:'2026-10-01T08:00:00Z', prompt:'LegacyArchive 项目', text:'旧回答', state:'done' },
        ...Array.from({ length:6 }, (_, i) => ({ id:'recent-' + i, at:'2026-10-20T08:00:00Z', prompt:'周历记录 ' + i, text:'已记录', state:'done' }))
      ]));
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('http://127.0.0.1:8766/', { waitUntil:'domcontentloaded' });
    await page.evaluate(() => show('ai'));
    await page.locator('#ai-memory-open').click();
    assert.equal(await page.locator('#ai-memory-dialog').evaluate((el) => el.open), true);
    assert.equal(await page.locator('#ai-memory-recent li').count(), 7);
    assert.match(await page.locator('#ai-memory-terms').textContent(), /legacyarchive/);
    assert.equal(await page.evaluate(() => extractQuestionKeywords('请检查 sk-12345678901234567890').length), 0);
    assert.equal(await page.evaluate(() => extractQuestionKeywords('联系 test@example.com').length), 0);
    await page.locator('#ai-memory-close').click();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('调整工具调用');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'done');
    assert.ok(requestBody);
    assert.equal(JSON.stringify(requestBody).includes('LegacyArchive'), false);
    assert.equal(JSON.stringify(requestBody).includes('legacyarchive'), false);
    assert.equal(Object.hasOwn(requestBody, 'memory'), false);
    await page.locator('#ai-memory-open').click();
    assert.match(await page.locator('#ai-memory-terms').textContent(), /工具/);
    await page.locator('#ai-memory-close').click();
    await page.evaluate(() => {
      localStorage.setItem('whq-personal-resume-v1', JSON.stringify({
        name:'测试用户', summary:'本机保存的个人简介', projects:'独有项目：浏览器本地简历读取', experience:'本机实习经历'
      }));
      renderResume();
    });
    assert.equal(await page.evaluate(() => recordsContextForAi().includes('独有项目')), false);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('你给我看看简历');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /我这里有两份简历/);
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), false);
    assert.equal(askRequests, 1);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('第一份');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /已在本机读取当前保存的简历/);
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), true);
    assert.match(await page.locator('#ai-resume-preview').textContent(), /独有项目.*浏览器本地简历读取/);
    assert.equal(askRequests, 1);
    await page.locator('#ai-resume-close').click();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('我想看第二份简历');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /已在本机读取平台模板简历/);
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), true);
    assert.doesNotMatch(await page.locator('#ai-resume-preview').textContent(), /独有项目：浏览器本地简历读取/);
    await page.locator('#ai-resume-close').click();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('请根据这个项目“简历”页面里保存的内容回答，不要读取桌面文件。如果你读不到这份简历，请直接告诉我，不要猜。');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /已在本机读取当前保存的简历/);
    assert.equal(await page.evaluate(() => aiRuns.at(-1).tools.length), 0);
    assert.equal(askRequests, 1);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('这个项目上传的简历页的项目经历有哪些？');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /独有项目：浏览器本地简历读取/);
    assert.equal(askRequests, 1);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('普通追问');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'done');
    assert.equal(JSON.stringify(requestBody.messages).includes('独有项目：浏览器本地简历读取'), false);
    assert.equal(JSON.stringify(requestBody.messages).includes('本机保存的个人简介'), false);
    assert.equal(requestBody.memory_terms.includes('工具'), true);
    assert.equal(requestBody.memory_terms.includes('legacyarchive'), false);
    assert.equal(askRequests, 2);
    await page.evaluate(() => { localStorage.removeItem('whq-personal-resume-v1'); renderResume(); });
    await page.locator('#ai-ask textarea[name="prompt"]').fill('这个项目的简历页保存了什么？');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('#ai-chat .run').last().textContent(), /没有保存上传或编辑后的简历/);
    assert.equal(askRequests, 2);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_project"]').check();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('项目操作测试');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'done');
    assert.equal(requestBody.memory_terms.includes('工具'), false);
    assert.equal(askRequests, 3);
    await page.locator('#ai-memory-open').click();
    await page.locator('#ai-memory-clear').click();
    assert.equal(await page.locator('#ai-memory-terms').textContent(), '暂无关键词');
    assert.equal(await page.locator('#ai-memory-recent li').count(), 12);
    await page.locator('#ai-memory-close').click();
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask input[name="local_project"]').uncheck();
    const chatCount = await page.evaluate(() => aiChats.length);
    await page.locator('#ai-chat-new').click();
    assert.equal(await page.locator('#ai-chat .agent-empty').count(), 1);
    assert.equal(await page.evaluate(() => aiChats.length), chatCount + 1);
    await page.locator('#ai-chat-new').click();
    assert.equal(await page.evaluate(() => aiChats.length), chatCount + 1);
    await page.locator('#ai-ask textarea[name="prompt"]').fill('NewChatIsolation');
    await page.locator('#ai-ask .send-btn').click();
    await page.waitForFunction(() => aiRuns.at(-1).state === 'done' && aiRuns.at(-1).prompt === 'NewChatIsolation');
    assert.equal(JSON.stringify(requestBody.messages).includes('\u666e\u901a\u8ffd\u95ee'), false);
    assert.equal(JSON.stringify(requestBody.messages).includes('\u8c03\u6574\u5de5\u5177\u8c03\u7528'), false);
    assert.equal(requestBody.messages.filter((item) => item.role === 'user').length, 1);
    await page.locator('#ai-chat-open').click();
    assert.equal(await page.locator('#ai-chat-dialog').evaluate((el) => el.open), true);
    assert.ok(await page.locator('.ai-chat-item').count() >= 2);
    await page.locator('.ai-chat-item').filter({ hasText: '\u4ee5\u5f80\u5bf9\u8bdd' }).click();
    assert.match(await page.locator('#ai-chat').textContent(), /LegacyArchive/);
    assert.equal((await page.locator('#ai-chat').textContent()).includes('NewChatIsolation'), false);
    assert.deepEqual(errors, []);
    await context.close();
    console.log('AI memory browser flow passed.');
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
