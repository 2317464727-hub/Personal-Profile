const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const { pathToFileURL } = require('node:url');
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 850 }, timezoneId: 'Asia/Shanghai' });
    await context.route('**/*', (route) => route.request().url().startsWith('file:') ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(__dirname, 'index.html')).href);
    await page.evaluate(() => show('week'));
    await page.evaluate(() => {
      const logs = loadUserLogs();
      logs.push({ id:'filter-agent', date:'2026-10-28', time:'10:00', end:'11:00', workspace:'agent', title:'代理工作区测试', body:'' });
      logs.push({ id:'filter-personal', date:'2026-10-28', time:'11:00', end:'12:00', workspace:'personal', title:'个人工作区测试', body:'' });
      saveUserLogs(logs);
      focusSpace = 'agent';
      renderCalendar();
      renderRail();
    });
    assert.equal(await page.locator('#calendar [data-id="filter-agent"]').count(), 1);
    assert.equal(await page.locator('#calendar [data-id="filter-personal"]').count(), 0);
    await page.evaluate(() => { focusSpace = 'all'; renderCalendar(); renderRail(); });
    await page.clock.setFixedTime(new Date('2026-10-28T09:19:00Z'));
    await page.evaluate(() => updateCurrentSlotButton());
    assert.match(await page.locator('[data-current-slot]').textContent(), /17:00–17:30/);
    await page.locator('[data-current-slot]').click();
    assert.equal(await page.locator('#week .log-form [name="date"]').inputValue(), '2026-10-28');
    assert.equal(await page.locator('#week .log-form [name="start"]').inputValue(), '17:00');
    assert.equal(await page.locator('#week .log-form [name="end"]').inputValue(), '17:30');
    assert.equal(await page.locator('[data-current-slot]').getAttribute('aria-pressed'), 'true');
    await page.clock.setFixedTime(new Date('2026-10-28T13:05:00Z'));
    await page.evaluate(() => updateCurrentSlotButton());
    assert.equal(await page.locator('[data-current-slot]').isDisabled(), true);
    assert.match(await page.locator('[data-current-slot]').textContent(), /当前不在/);
    await page.locator('#week .log-form [name="title"]').fill('画布位置测试');
    await page.locator('#week .log-form [data-range="13:00-18:00"]').click();
    assert.equal(await page.locator('#week .log-form [name="start"]').inputValue(), '13:00');
    assert.equal(await page.locator('#week .log-form [name="end"]').inputValue(), '18:00');
    await page.locator('#week .log-form [data-result="通过"]').click();
    assert.match(await page.locator('#week .log-form [name="body"]').inputValue(), /结果：通过/);
    await page.locator('#week-file-image').setInputFiles({
      name: 'sample.png', mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/XHcAAAAASUVORK5CYII=', 'base64'),
    });
    await page.locator('#week-file-doc').setInputFiles({
      name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('test document'),
    });
    await page.locator('#week-file-video').setInputFiles({
      name: 'sample.mp4', mimeType: 'video/mp4', buffer: Buffer.from('test video'),
    });
    await page.locator('#week .week-file').nth(2).waitFor();
    assert.equal(await page.locator('#week .week-file').count(), 3);
    assert.equal(await page.locator('#week .week-file-view img').count(), 1);
    assert.equal(await page.locator('#week .week-file-view pre').count(), 1);
    assert.equal(await page.locator('#week .week-file-view video').count(), 1);
    const geometry = await page.evaluate(() => {
      const stage = document.querySelector('#week-canvas-stage').getBoundingClientRect();
      const note = document.querySelector('#week-canvas textarea').getBoundingClientRect();
      const card = document.querySelector('#week .week-file').getBoundingClientRect();
      return { inside: card.top >= stage.top && card.top < stage.bottom, beside: card.left >= note.right };
    });
    assert.deepEqual(geometry, { inside: true, beside: true });
    await page.locator('#week .log-form [type="submit"]').click();
    const recordId = await page.evaluate(() => loadUserLogs().find((item) => item.title === '画布位置测试').id);
    const grip = page.locator('#week .week-file-top').first();
    const rect = await grip.boundingBox();
    await page.mouse.move(rect.x + 60, rect.y + 12);
    await page.mouse.down();
    await page.mouse.move(rect.x + 100, rect.y + 92, { steps: 8 });
    await page.mouse.up();
    const moved = await page.evaluate((id) => loadUserLogs().find((item) => item.id === id).attachments[0], recordId);
    assert.ok(moved.x > 0 && moved.y >= 80, 'drag position should be saved with the record');
    await page.reload();
    await page.evaluate((id) => { show('week'); loadById(id); }, recordId);
    await page.locator('#week .week-file').nth(2).waitFor();
    const restored = await page.locator('#week .week-file').first().evaluate((el) => ({ x: parseFloat(el.style.left), y: parseFloat(el.style.top) }));
    assert.equal(restored.x, moved.x);
    assert.equal(restored.y, moved.y);
    await page.setViewportSize({ width: 390, height: 780 });
    assert.equal(await page.locator('#week .log-form .log-actions').evaluate((el) => getComputedStyle(el).position), 'sticky');
    const mobile = await page.evaluate(() => {
      const stage = document.getElementById('week-canvas-stage');
      const form = document.querySelector('#week .log-form').getBoundingClientRect();
      return { scrollable: stage.scrollWidth > stage.clientWidth, cardVisible: !!document.querySelector('#week .week-file'), formFits: form.left >= 0 && form.right <= innerWidth };
    });
    assert.deepEqual(mobile, { scrollable: true, cardVisible: true, formFits: true });
    assert.deepEqual(errors, []);
    console.log('Weekly canvas placement, drag persistence and narrow viewport: OK');
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
