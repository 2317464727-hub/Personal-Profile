const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const { pathToFileURL } = require('node:url');
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({ executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless:true });
  try {
    const context = await browser.newContext({ viewport:{ width:1280, height:850 } });
    await context.route('**/*', (route) => route.request().url().startsWith('file:') ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(__dirname, 'index.html')).href);
    await page.evaluate(() => {
      show('ai');
      aiHealth = { ok:true, model:'test-model' };
      renderAiConnectionStatus();
      mindNodes = [{ id:'test-doc', kind:'doc', ext:'txt', name:'notes.txt', preview:'任务说明\napi_key: sk-abcdefghijklmnop\ntest@example.com\n13800138000\n正常段落' }];
      renderMind();
    });
    assert.match(await page.locator('#ai-link').textContent(), /模型接口就绪.*本机资料未授权/);
    assert.doesNotMatch(await page.locator('#note-media .doc-paper').textContent(), /sk-abcdefghijklmnop/);
    assert.doesNotMatch(await page.locator('#note-media .doc-paper').textContent(), /test@example.com|13800138000/);
    assert.doesNotMatch(await page.evaluate(() => editorContextForAi()), /sk-abcdefghijklmnop/);
    await page.locator('[data-doc-reveal="test-doc"]').click();
    assert.match(await page.locator('#note-media .doc-paper').textContent(), /sk-abcdefghijklmnop/);
    assert.doesNotMatch(await page.evaluate(() => editorContextForAi()), /sk-abcdefghijklmnop/);
    await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask [name="local_records"]').check();
    assert.match(await page.locator('#ai-link').textContent(), /将发送：周历记录/);
    if (!await page.locator('#local-access-menu').evaluate((el) => el.open)) await page.locator('#local-access-menu summary').click();
    await page.locator('#ai-ask [name="local_files"]').check();
    assert.match(await page.locator('#ai-link').textContent(), /按需访问：本机文件/);
    assert.deepEqual(errors, []);
    console.log('AI access status and document redaction: OK');
  } finally { await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
