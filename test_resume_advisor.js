const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');

let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({ executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless:true });
  try {
    const context = await browser.newContext({ viewport:{ width:1280, height:850 } });
    let adviceRequests = 0;
    let requestBody;
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/resume/advise') {
        adviceRequests++;
        requestBody = JSON.parse(route.request().postData());
        return route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify({
          analysis:[{ text:'把尚未测试的范围写清楚', source_ids:['work-1'] }],
          suggestions:[{ target:'experience', text:'示例科技有限公司｜实习生\n2026.09 — 至今｜北京\n授权接入\n- 核对授权范围并记录回调差异；发布能力尚未测试。', source_ids:['work-1'], structured:true, checked:false }]
        }) });
      }
      if (url.pathname === '/api/ask') return route.abort();
      if (url.hostname === '127.0.0.1') return route.continue();
      return route.abort();
    });
    await require('./test_storage_mock')(context);
    await context.addInitScript(() => {
      if (localStorage.getItem('advisor-test-init')) return;
      localStorage.setItem('advisor-test-init', '1');
      localStorage.setItem('whq-recent-work-2026-10-27-v1', '1');
      localStorage.setItem('whq-personal-resume-v1', JSON.stringify({
        name:'测试用户', phone:'12345678901', email:'test@example.com', summary:'参与平台接入与测试', experience:'示例科技有限公司｜实习生\n2026.09 — 至今｜北京\n核对授权流程', projects:'个人平台', skills:'Python'
      }));
      localStorage.setItem('whq-resume-work-additions-v1', JSON.stringify([{ id:'prior-1', target:'experience', text:'整理项目需求和测试清单。', sourceIds:['work-1'], structured:true }]));
      localStorage.setItem('whq-personal-logs-v1', JSON.stringify([{
        id:'work-1', date:new Date().toLocaleDateString('sv-SE'), time:'10:00', end:'11:00', workspace:'agent',
        title:'核对授权范围', body:'发现回调差异；发布尚未测试', source:'user'
      }]));
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(process.env.PERSONAL_TEST_URL || 'http://127.0.0.1:8766/', { waitUntil:'domcontentloaded' });
    await page.waitForFunction(() => typeof show === 'function');
    await page.evaluate(() => show('ai'));
    await page.locator('#ai-ask textarea[name="prompt"]').fill('根据近 30 天工作优化第一份简历');
    await page.locator('#ai-ask .send-btn').click();
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), true);
    assert.equal(await page.locator('#ai-resume-range').inputValue(), '30');
    assert.equal(await page.locator('#ai-resume-consent').isVisible(), true);
    assert.equal(adviceRequests, 0);
    assert.equal(await page.locator('#ai-resume-apply').isEnabled(), false);
    await page.locator('#ai-resume-range').selectOption('14');
    assert.equal(await page.locator('#ai-resume-consent').isVisible(), true);
    assert.equal(adviceRequests, 0);
    await page.locator('#ai-resume-close').click();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('根据近 30 天工作优化第一份简历');
    await page.locator('#ai-ask .send-btn').click();
    assert.equal(await page.locator('#ai-resume-range').inputValue(), '30');
    assert.equal(await page.locator('#ai-resume-consent').isVisible(), true);
    await page.setViewportSize({ width:390, height:844 });
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth + 1), true);
    await page.setViewportSize({ width:1280, height:850 });
    await page.locator('#ai-resume-consent-send').click();
    await page.locator('#ai-resume-insights').waitFor({ state:'visible' });
    assert.equal(adviceRequests, 1);
    assert.equal(requestBody.consent, true);
    assert.equal(requestBody.resume.summary, '参与平台接入与测试');
    assert.equal(requestBody.logs.some((item) => item.id === 'work-1'), true);
    for (const key of ['name', 'phone', 'email', 'photo']) assert.equal(Object.hasOwn(requestBody.resume, key), false);
    assert.match(await page.locator('#ai-resume-insights').textContent(), /尚未测试.*来源：核对授权范围/);
    assert.match(await page.locator('#ai-resume-proposals').textContent(), /来源：.*核对授权范围/);
    assert.equal(await page.locator('.resume-proposal input[type="checkbox"]').isChecked(), false);
    assert.equal(await page.locator('#ai-resume-apply').isEnabled(), false);
    await page.locator('.resume-proposal textarea').fill('示例科技有限公司｜实习生\n2026.09 — 至今｜北京\n授权接入\n- 核对授权范围并记录回调差异；发布能力尚未测试。\n- 整理验证记录。');
    await page.evaluate(() => { show('week'); show('ai'); });
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), true);
    assert.match(await page.locator('.resume-proposal textarea').inputValue(), /整理验证记录/);
    assert.match(await page.locator('#ai-resume-insights').textContent(), /尚未测试/);
    await page.reload({ waitUntil:'domcontentloaded' });
    await page.waitForFunction(() => document.getElementById('ai-resume-dialog').open);
    assert.match(await page.locator('.resume-proposal textarea').inputValue(), /整理验证记录/);
    await page.locator('#ai-resume-close').click();
    await page.reload({ waitUntil:'domcontentloaded' });
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), false);
    assert.equal(await page.locator('#ai-resume-open').textContent(), '继续简历草稿');
    await page.locator('#ai-resume-open').click();
    assert.match(await page.locator('.resume-proposal textarea').inputValue(), /整理验证记录/);
    await page.locator('.resume-proposal input[type="checkbox"]').check();
    assert.equal(await page.locator('#ai-resume-apply').textContent(), '确认写入 1 项');
    await page.locator('#ai-resume-apply').click();
    const additions = await page.evaluate(() => JSON.parse(localStorage.getItem('whq-resume-work-additions-v1')));
    assert.equal(additions.length, 2);
    assert.equal(additions[1].sourceIds[0], 'work-1');
    assert.match(additions[1].text, /发布能力尚未测试/);
    assert.match(await page.locator('#resume-ai-experience').textContent(), /授权接入.*整理验证记录/s);
    assert.equal(JSON.parse(await page.evaluate(() => localStorage.getItem('whq-personal-resume-v1'))).experience, '示例科技有限公司｜实习生\n2026.09 — 至今｜北京\n核对授权流程');
    assert.equal(await page.evaluate(() => localStorage.getItem('whq-resume-advice-review-v1')), null);
    await page.reload({ waitUntil:'domcontentloaded' });
    assert.equal(await page.locator('#resume').evaluate((section) => section.classList.contains('active')), true);
    assert.deepEqual(errors, []);
    console.log('Resume advice consent, source-backed draft and confirmation: OK');
  } finally { await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
