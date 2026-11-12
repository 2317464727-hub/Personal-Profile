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
    await page.evaluate(() => show('home'));
    await page.setViewportSize({ width:1440, height:900 });
    const sheet = await page.locator('#home .home-page').evaluate((el) => el.getBoundingClientRect().toJSON());
    assert.ok(sheet.width >= 1400 && sheet.left <= 1 && sheet.right >= 1439 && sheet.right <= 1441, JSON.stringify(sheet));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= 1441), true);
    await page.setViewportSize({ width:1280, height:850 });
    assert.equal(await page.locator('#home .home-focus-item').count(), 2);
    assert.equal(await page.locator('#home-recent-list [data-home-log]').count(), 3);
    const title = await page.locator('#home-recent-list [data-home-log]').first().locator('strong').textContent();
    const firstId = await page.locator('#home-recent-list [data-home-log]').first().getAttribute('data-home-log');
    await page.locator('#home-recent-list [data-home-hide]').first().click();
    assert.equal(await page.locator('#home-recent-list [data-home-log="' + firstId + '"]').count(), 0);
    assert.equal(await page.locator('#home-recent-list [data-home-log]').count(), 3);
    await page.locator('#home-record-manage summary').click();
    await page.locator('#home-record-manage [data-home-visibility="' + firstId + '"]').click();
    assert.equal(await page.locator('#home-recent-list [data-home-log="' + firstId + '"]').count(), 1);
    await page.locator('#home-recent-list [data-home-log]').first().click();
    assert.equal(await page.locator('#week').evaluate((el) => el.classList.contains('active')), true);
    assert.equal(await page.evaluate(() => draft.title), title);
    await page.evaluate(() => show('home'));
    await page.locator('#home-open-resume').click();
    assert.equal(await page.locator('#resume').evaluate((el) => el.classList.contains('active')), true);
    await page.evaluate(() => show('home'));
    await page.locator('#home-open-intern').click();
    assert.equal(await page.locator('#intern').evaluate((el) => el.classList.contains('active')), true);
    await page.evaluate(() => show('home'));
    await page.locator('#home-edit').click();
    assert.equal(await page.locator('#home-editor').evaluate((dialog) => dialog.open), true);
    await page.locator('#profile-form [name="name"]').fill('测试用户');
    await page.locator('#profile-form [name="role"]').fill('产品工程实习生');
    await page.locator('#profile-form [name="company"]').fill('测试团队');
    await page.locator('#profile-form [name="headline"]').fill('新的个人标题');
    await page.locator('#profile-form [name="intro"]').fill('新的个人介绍');
    await page.locator('#profile-form [name="school"]').fill('测试学校');
    await page.locator('#profile-form [name="email"]').fill('test@example.com');
    await page.locator('#home-add-focus').click();
    await page.locator('#home-focus-editor .home-focus-edit').last().locator('[name="title"]').fill('新增工作重点');
    await page.locator('#home-focus-editor [data-remove-focus="1"]').click();
    assert.equal(await page.locator('#home-focus-editor .home-focus-edit').count(), 2);
    await page.locator('#profile-form [type="submit"]').click();
    assert.equal(await page.evaluate(() => loadProfile().school), '测试学校');
    assert.equal(await page.locator('#home-name').textContent(), '测试用户');
    assert.match(await page.locator('#home .home-role').textContent(), /产品工程实习生.*测试团队/);
    assert.equal(await page.locator('#home-headline').textContent(), '新的个人标题');
    assert.equal(await page.locator('#intro').textContent(), '新的个人介绍');
    assert.match(await page.locator('#home-focus-grid').textContent(), /新增工作重点/);
    assert.doesNotMatch(await page.locator('#home-focus-grid').textContent(), /库存风险工作台/);
    assert.match(await page.locator('#home-contact-list').textContent(), /测试学校.*test@example.com/s);
    await page.evaluate(() => show('resume'));
    assert.equal(await page.locator('#resume-name').textContent(), '测试用户');
    await page.reload();
    await page.evaluate(() => show('home'));
    assert.equal(await page.locator('#home-name').textContent(), '测试用户');
    assert.match(await page.locator('#home-focus-grid').textContent(), /新增工作重点/);
    await page.locator('#home-edit').click();
    await page.locator('#profile-form [name="name"]').fill('未保存姓名');
    await page.locator('#home-editor-cancel').click();
    assert.equal(await page.locator('#home-name').textContent(), '测试用户');
    const day = await page.locator('body').evaluate((el) => getComputedStyle(el).backgroundColor);
    await page.evaluate(() => applyTheme('night'));
    const night = await page.locator('body').evaluate((el) => getComputedStyle(el).backgroundColor);
    assert.notEqual(day, night);
    await page.setViewportSize({ width:390, height:780 });
    await page.locator('#home-edit-contact').click();
    const editorFits = await page.locator('#home-editor').evaluate((dialog) => {
      const rect = dialog.getBoundingClientRect();
      const footer = dialog.querySelector('.home-editor-actions').getBoundingClientRect();
      return rect.left >= 0 && rect.right <= innerWidth + 1 && footer.bottom <= innerHeight + 1;
    });
    assert.equal(editorFits, true);
    await page.locator('#home-editor-close').click();
    await page.evaluate(() => {
      const profile = loadProfile();
      profile.name = 'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ';
      profile.headline = 'UnbrokenLongHeadlineUnbrokenLongHeadlineUnbrokenLongHeadline';
      profile.focusItems[0].title = 'UnbrokenLongFocusTitleUnbrokenLongFocusTitleUnbrokenLongFocusTitle';
      localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
      renderHome();
    });
    const mobileFits = await page.evaluate(() => {
      const name = document.querySelector('#home-name').getBoundingClientRect();
      return document.documentElement.scrollWidth <= innerWidth + 1 && name.left >= 0 && name.right <= innerWidth;
    });
    assert.equal(mobileFits, true);
    await page.evaluate(() => {
      const date = isoDate(new Date());
      localStorage.setItem(LOG_KEY, JSON.stringify([
        { id:'chart-pass', date, time:'09:00', end:'09:30', workspace:'agent', title:'通过项', body:'结果：通过。' },
        { id:'chart-fail', date, time:'10:00', end:'10:30', workspace:'agent', title:'失败项', body:'结果：失败。' },
        { id:'chart-untested', date, time:'11:00', end:'11:30', workspace:'agent', title:'未测项', body:'结果：没测。' },
        { id:'chart-unmarked', date, time:'12:00', end:'12:30', workspace:'agent', title:'未标注项', body:'还在核对。' }
      ]));
      localStorage.setItem(RESUME_KEY, JSON.stringify({ summary:'个人优势\n工作上：能独立拆解问题并保留验证记录。' }));
      aiRuns.push({ id:'chart-ai', at:new Date().toISOString(), prompt:'测试', tools:[{ id:'call-1' }], state:'done' });
      renderHome();
    });
    await page.locator('[data-home-range="week"]').click();
    const chartRows = await page.locator('#home-outcome-list .home-outcome-row').allTextContents();
    assert.deepEqual(chartRows.map((row) => row.replace(/\s/g, '')), ['通过1', '未通过1', '没测1', '未标注1']);
    assert.equal(await page.locator('#home-outcome-note').textContent(), '已标注结果 3 / 4 条');
    assert.match(await page.locator('#home-recent-list [data-home-log="chart-unmarked"]').textContent(), /未标注/);
    assert.match(await page.locator('#home-strength-list').textContent(), /独立拆解问题/);
    assert.equal(await page.locator('#home-ai-total').textContent(), '1');
    assert.equal(await page.locator('#home-ai-tools').textContent(), '1 次工具调用');
    const generated = await page.evaluate(() => [
      normalizeRecord({ title:'通过', body:'已经验证。', result:'通过' }),
      normalizeRecord({ title:'失败', body:'实际测试未成功。', result:'失败' }),
      normalizeRecord({ title:'无结果', body:'完成配置。' }),
      normalizeRecord({ title:'冲突', body:'结果：失败。', result:'通过' })
    ].map((item) => ({ body:item.body, outcome:homeOutcome(item) })));
    assert.deepEqual(generated, [
      { body:'已经验证。\n结果：通过。', outcome:'pass' },
      { body:'实际测试未成功。\n结果：失败。', outcome:'fail' },
      { body:'完成配置。\n结果：没测。', outcome:'untested' },
      { body:'结果：没测。', outcome:'untested' }
    ]);
    const savedAiBody = await page.evaluate(() => {
      const saved = saveAiRecords([{ date:isoDate(new Date()), time:'15:00', end:'15:30', workspace:'personal', title:'AI 写入校验', body:'配置已完成。' }]);
      renderHome();
      return saved[0]?.body;
    });
    assert.equal(savedAiBody, '配置已完成。\n结果：没测。');
    assert.match(await page.locator('#home-outcome-note').textContent(), /已标注结果 4 \/ 5 条/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.deepEqual(errors, []);
    console.log('Personal center content, navigation, profile form and mobile layout: OK');
  } finally { await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
