const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const { pathToFileURL } = require('node:url');
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

const original = {
  name:'测试用户', role:'AI 应用开发',
  experience:'工作上：\n深耕 AI 大模型与 Agent 开发，持续跟进前沿技术；踏实负责、执行力强，做到当日事当日毕。\n学习上：\n热衷钻研新技术，自学速度快，可快速完成技术落地与工程实现。\n生活上：\n性格开朗，适应力强，擅长沟通协作，抗压能力良好。\n技能证书\n能力证书：\n通过大学英语四级、普通话二级乙等、通过国家计算机二级。\n荣誉奖项\n特等奖学金，一等奖学金，二等奖学金，全国大学生电子商务“创新、创意及创业”挑战赛\n山西省二等奖，全国大学生数学建模竞赛山西省二等奖，挑战杯中国大学生创业计划竞赛山西省三等奖，中国\n大学生\n计算机设计大赛山西省三等奖。',
  projects:'2026.05-至今 本地 Agent — 应用开发\n项目介绍：构建本地工具与任务流程\n核心设计：\n- 任务记录与工作区管理',
  skills:'- 熟悉 Python 与 Agent 工具调用\n- 熟悉 CSV 数据处理'
};

original.experience += '\n熟悉 Agent 基本原理和核心组件，了解规划、执行、工具调用、结果观察、继续推理、可观测性的闭环。\n熟悉 ReAct、Reflection、Tool Use、Function Call、MCP、多 Agent 协作等核心机制。';

async function main() {
  const browser = await chromium.launch({ executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless:true });
  try {
    const context = await browser.newContext({ viewport:{ width:1366, height:1000 } });
    await context.route('**/*', (route) => route.request().url().startsWith('file:') ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(__dirname, 'index.html')).href);
    await page.evaluate((resume) => {
      localStorage.setItem(RESUME_KEY, JSON.stringify(resume));
      localStorage.setItem(RESUME_LEGACY_AI_MIGRATED_KEY, '1');
      renderResume(); show('resume');
    }, original);
    const photo = page.locator('#resume .resume-photo');
    assert.equal(await photo.isVisible(), false);
    const portrait = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 60; canvas.height = 80;
      const context = canvas.getContext('2d');
      context.fillStyle = '#d5e2e5'; context.fillRect(0, 0, 60, 80);
      context.fillStyle = '#246b75'; context.fillRect(20, 18, 20, 36);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#resume-photo-file').setInputFiles({ name:'portrait.png', mimeType:'image/png', buffer:Buffer.from(portrait, 'base64') });
    assert.equal(await photo.isVisible(), true);
    assert.match(await page.evaluate(() => localStorage.getItem(RESUME_PHOTO_KEY)), /^data:image\/jpeg;base64,/);
    assert.match(await page.evaluate(() => resumePdfPayload().photo), /^data:image\/jpeg;base64,/);
    const desktopPhoto = await photo.boundingBox();
    assert.ok(desktopPhoto.width <= 58 && desktopPhoto.height <= 76);
    assert.ok(Math.abs(desktopPhoto.width / desktopPhoto.height - .75) < .02);
    assert.ok(desktopPhoto.x > (await page.locator('#resume-name').boundingBox()).x);
    assert.ok(desktopPhoto.y < (await page.locator('#resume .resume-layout').boundingBox()).y);
    const square = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 80; canvas.height = 80;
      const context = canvas.getContext('2d');
      context.fillStyle = '#fff'; context.fillRect(0, 0, 80, 80);
      context.fillStyle = '#7440b8'; context.fillRect(16, 16, 48, 48);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#resume-photo-file').setInputFiles({ name:'logo.png', mimeType:'image/png', buffer:Buffer.from(square, 'base64') });
    await page.waitForFunction(() => document.getElementById('resume-photo').naturalWidth === 80);
    const squarePhoto = await photo.boundingBox();
    assert.ok(Math.abs(squarePhoto.width - squarePhoto.height) < 1);
    assert.ok(squarePhoto.width <= 58);
    assert.equal(await photo.evaluate((image) => getComputedStyle(image).borderTopWidth), '0px');
    assert.equal(await page.locator('#resume-strengths .resume-strength').count(), 3);
    assert.equal(await page.locator('#resume-experience-section').isVisible(), false);
    assert.equal(await page.locator('#resume-qualifications li').count(), 3);
    assert.equal(await page.locator('#resume-awards li').count(), 7);
    assert.doesNotMatch(await page.locator('#resume-awards').textContent(), /Agent|ReAct/);
    assert.match(await page.locator('#resume-skills-imported').textContent(), /熟悉 Agent 基本原理和核心组件，了解规划、执行、工具调用/);
    assert.equal(await page.locator('#resume-awards li').last().textContent(), '中国大学生计算机设计大赛山西省三等奖');
    assert.match(await page.locator('#resume-awards li').nth(3).textContent(), /“创新、创意及创业”挑战赛山西省二等奖/);
    assert.equal(await page.locator('#resume-awards strong').count(), 7);
    assert.deepEqual(await page.evaluate(() => loadImportedResume()), original);
    const companyRetained = await page.evaluate(() => resumeDisplaySections({ experience:'示例有限公司｜实习生\n2026.09 — 至今\n工作上：负责接口联调' }).experience);
    assert.match(companyRetained, /工作上：负责接口联调/);
    const screenshotDir = process.argv[2];
    if (screenshotDir) await page.screenshot({ path:path.join(screenshotDir, 'resume-layout-desktop.png'), fullPage:true });
    await page.locator('[data-resume-edit-source="awards"]').click();
    const awardsEditor = page.locator('#resume-import-form [name="awards"]');
    assert.match(await awardsEditor.inputValue(), /全国大学生数学建模竞赛山西省二等奖/);
    assert.doesNotMatch(await page.locator('#resume-import-form [name="experience"]').inputValue(), /荣誉奖项/);
    assert.match(await page.locator('#resume-import-form [name="qualifications"]').inputValue(), /大学英语四级/);
    assert.match(await page.locator('#resume-import-form [name="strengths"]').inputValue(), /工作上：/);
    assert.equal(await awardsEditor.evaluate((el) => document.activeElement === el), true);
    await awardsEditor.fill((await awardsEditor.inputValue()).replace('特等奖学金', '国家奖学金'));
    await page.locator('#resume-dialog-submit').click();
    assert.match(await page.locator('#resume-awards').textContent(), /国家奖学金/);
    assert.doesNotMatch(await page.locator('#resume-awards').textContent(), /Agent|ReAct/);
    const saved = await page.evaluate(() => loadImportedResume());
    assert.equal((saved.skills.match(/荣誉奖项/g) || []).length, 1);
    assert.doesNotMatch(saved.experience, /荣誉奖项|能力证书/);
    await page.reload();
    await page.evaluate(() => show('resume'));
    assert.equal(await photo.isVisible(), true);
    assert.match(await page.locator('#resume-awards').textContent(), /国家奖学金/);
    await page.locator('[data-resume-edit-source="qualifications"]').click();
    assert.equal(await page.locator('#resume-import-form [name="qualifications"]').evaluate((el) => document.activeElement === el), true);
    await page.locator('#resume-import-cancel').click();
    await page.evaluate(() => openResumePreview({ skills:'荣誉奖项\n数学建模一等奖\n熟悉 Python 与 FastAPI。' }, '', 'import'));
    assert.equal(await page.locator('#resume-import-form [name="awards"]').inputValue(), '数学建模一等奖');
    assert.equal(await page.locator('#resume-import-form [name="skills"]').inputValue(), '熟悉 Python 与 FastAPI。');
    await page.locator('#resume-import-cancel').click();
    await page.setViewportSize({ width:390, height:844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    const mobilePhoto = await photo.boundingBox();
    assert.ok(mobilePhoto.x + mobilePhoto.width <= 390);
    assert.ok(mobilePhoto.x > (await page.locator('#resume-name').boundingBox()).x);
    assert.equal(await page.locator('#resume-strengths .resume-strength').first().evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length), 1);
    if (screenshotDir) await page.screenshot({ path:path.join(screenshotDir, 'resume-layout-mobile.png'), fullPage:true });
    await page.evaluate(() => applyTheme('night'));
    assert.equal(await page.locator('#resume-qualifications li').first().isVisible(), true);
    if (screenshotDir) await page.screenshot({ path:path.join(screenshotDir, 'resume-layout-night.png'), fullPage:true });
    await page.setViewportSize({ width:1366, height:1000 });
    await page.emulateMedia({ media:'print' });
    assert.equal(await page.locator('#resume-strengths').isVisible(), true);
    assert.equal(await page.locator('#resume-awards').isVisible(), true);
    assert.equal(await page.locator('[data-resume-edit-source="awards"]').isVisible(), false);
    await page.emulateMedia({ media:'screen' });
    await page.locator('#resume-photo-remove').click();
    assert.equal(await photo.isVisible(), false);
    assert.equal(await page.evaluate(() => resumePdfPayload().photo), '');
    assert.deepEqual(errors, []);
    console.log('Resume personal sections, wrapped awards, source editing, mobile and print: OK');
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
