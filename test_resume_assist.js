const assert = require('node:assert/strict');
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
    const context = await browser.newContext({ viewport: { width: 1280, height: 850 } });
    let aiRequests = 0;
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/ask') { aiRequests++; return route.abort(); }
      if (url.hostname === '127.0.0.1') return route.continue();
      return route.abort();
    });
    await require('./test_storage_mock')(context);
    await context.addInitScript(() => {
      if (localStorage.getItem('resume-test-init')) return;
      localStorage.setItem('resume-test-init', '1');
      localStorage.setItem('whq-recent-work-2026-10-27-v1', '1');
      localStorage.setItem('whq-personal-resume-v1', JSON.stringify({
        name: '测试用户', summary: '原有简介',
        experience: '工作上：负责平台接入与测试\n学习上：持续整理技术方案',
        projects: '2026.05-至今 RIOT Claude — 本地 AI Agent 系统\n项目介绍：实现 Agent 协作\n核心设计：\n□ 工具调用与状态管理\n2026.03-2026.05 金融保险 RAG — 智能问答系统\n项目结果：完成检索链路',
        skills: '□ 熟悉 Agent 基本原理\n□ 熟悉 Python 与 FastAPI'
      }));
      localStorage.setItem('whq-personal-logs-v1', JSON.stringify([{
        id: 'resume-test-record', date: new Date(Date.now() - 24 * 60 * 60 * 1000).toLocaleDateString('sv-SE'), time: '10:00', end: '11:00',
        workspace: 'personal', title: '核对平台授权与发布流程', body: '整理 OAuth 权限配置，发布能力仍待实测', source: 'user'
      }]));
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('http://127.0.0.1:8766/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => typeof show === 'function');
    await page.evaluate(() => { show('resume'); renderResume(); });
    assert.equal(await page.locator('#resume .resume-imported-project').count(), 2);
    assert.equal(await page.locator('#resume-strengths .resume-strength').count(), 2);
    assert.equal(await page.locator('#resume-experience-section').isVisible(), false);
    assert.equal(await page.locator('#resume-skills-imported .resume-skill-group li').count(), 2);
    assert.match(await page.locator('#resume .resume-imported-project').first().textContent(), /RIOT Claude/);
    await page.evaluate(() => show('ai'));
    await page.locator('#ai-ask textarea[name="prompt"]').fill('帮我把这一个月的活放在我的简历里面');
    await page.locator('#ai-ask .send-btn').click();
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), true);
    await page.locator('#ai-resume-preview').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#ai-resume-range').inputValue(), '30');
    await page.waitForFunction(() => document.getElementById('ai-resume-state').textContent.includes('涵盖'));
    assert.match(await page.locator('#ai-resume-preview').textContent(), /北京四方小仓科技有限公司/);
    assert.match(await page.locator('#ai-resume-count').textContent(), /已检查 \d+ 条近期记录/);
    assert.match(await page.locator('#ai-resume-state').textContent(), /涵盖 \d+ 条工作记录/);
    assert.equal(await page.locator('#ai-resume-sources input').count(), 0);
    await page.setViewportSize({ width: 390, height: 780 });
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const footer = el.querySelector('.resume-assist-footer').getBoundingClientRect();
      return rect.right <= innerWidth + 1 && footer.bottom <= innerHeight + 1;
    }), true);
    await page.setViewportSize({ width: 1280, height: 850 });
    await page.locator('#ai-resume-close').click();
    await page.locator('#ai-ask textarea[name="prompt"]').fill('帮我结合这几天的工作 你帮我总结一下写道简历里面');
    await page.locator('#ai-ask .send-btn').click();
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((dialog) => dialog.open), true);
    await page.locator('#ai-resume-preview').waitFor({ state: 'visible' });
    assert.equal(aiRequests, 0);
    assert.equal(await page.evaluate(() => isResumeWriteRequest('请总结我的简历内容')), false);
    await page.locator('#ai-resume-close').click();
    await page.locator('#ai-resume-open').click();
    await page.locator('#ai-resume-generate').click();
    try {
      await page.locator('#ai-resume-preview').waitFor({ state: 'visible', timeout: 5000 });
    } catch (error) {
      throw new Error('No proposal: ' + await page.locator('#ai-resume-state').textContent() + '; selected=' + await page.locator('#ai-resume-count').textContent() + '; browser errors=' + errors.join(' | '), { cause: error });
    }
    await page.locator('#ai-resume-view').click();
    const proposals = page.locator('.resume-proposal');
    const proposalTexts = await proposals.locator('textarea').all();
    let personalIndex = -1;
    for (let i = 0; i < proposalTexts.length; i++) {
      if ((await proposalTexts[i].inputValue()).includes('核对平台授权与发布流程')) { personalIndex = i; break; }
    }
    assert.ok(personalIndex >= 0, 'Personal work record is included in the generated draft');
    const personalProposal = proposals.nth(personalIndex);
    assert.match(await personalProposal.locator('textarea').inputValue(), /核对平台授权与发布流程/);
    for (let i = 0; i < await proposals.count(); i++) await proposals.nth(i).locator('input[type="checkbox"]').uncheck();
    await personalProposal.locator('input[type="checkbox"]').check();
    await personalProposal.locator('textarea').fill('核对 OAuth 权限配置，整理发布流程与待验证事项');
    await personalProposal.locator('select').selectOption('experience');
    await page.locator('#ai-resume-apply').click();
    assert.match(await page.locator('#resume-strengths').textContent(), /工作上负责平台接入与测试/);
    assert.match(await page.locator('#resume-ai-experience').textContent(), /核对 OAuth 权限配置/);
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('whq-resume-work-additions-v1')));
    assert.equal(stored.length, 1);
    assert.ok(stored[0].sourceIds.includes('resume-test-record'));
    assert.equal(JSON.parse(await page.evaluate(() => localStorage.getItem('whq-personal-resume-v1'))).experience, '工作上：负责平台接入与测试\n学习上：持续整理技术方案');
    await page.evaluate(() => show('ai'));
    await page.locator('#ai-resume-open').click();
    assert.equal(await page.evaluate(() => resumeAssistCandidateLogs().some((item) => item.id === 'resume-test-record')), false);
    await page.locator('#ai-resume-close').click();
    await page.setViewportSize({ width: 390, height: 780 });
    await page.locator('#ai-resume-open').click();
    const fits = await page.locator('#ai-resume-dialog').evaluate((el) => el.getBoundingClientRect().right <= innerWidth + 1);
    assert.equal(fits, true);
    await page.locator('#ai-resume-close').click();
    await page.evaluate(() => show('resume'));
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.locator('#resume-ai-experience .resume-ai-entry p').isVisible(), true);
    assert.equal(await page.locator('#resume-ai-experience .resume-ai-entry-meta').isVisible(), false);
    await page.emulateMedia({ media: 'screen' });
    await page.locator('#resume-ai-experience [data-resume-addition-action="edit"]').click();
    await page.locator('#resume-ai-experience textarea').fill('补充后的平台授权与发布流程记录');
    await page.locator('#resume-ai-experience .resume-ai-entry-actions button').last().click();
    assert.match(await page.locator('#resume-ai-experience').textContent(), /补充后的平台授权/);
    page.once('dialog', (dialog) => dialog.accept());
    await page.locator('#resume-ai-experience [data-resume-addition-action="remove"]').click();
    assert.equal(await page.locator('#resume-ai-experience .resume-ai-entry').count(), 0);
    assert.match(await page.locator('#resume-strengths').textContent(), /工作上负责平台接入与测试/);
    await page.evaluate(() => {
      localStorage.removeItem('whq-personal-resume-v1');
      localStorage.removeItem('whq-resume-work-additions-v1');
      show('resume');
      renderResume();
    });
    await page.locator('#resume-edit').click();
    assert.equal(await page.locator('#resume-dialog-title').textContent(), '直接编辑简历');
    assert.match(await page.locator('#resume-import-form textarea[name="summary"]').inputValue(), /围绕业务流程/);
    assert.match(await page.locator('#resume-import-form textarea[name="projects"]').inputValue(), /社交内容发布平台接入/);
    await page.locator('#resume-import-form textarea[name="summary"]').fill('这是我在当前页面直接修改后的个人简介。');
    await page.locator('#resume-dialog-submit').click();
    assert.equal(await page.locator('#resume-summary').textContent(), '这是我在当前页面直接修改后的个人简介。');
    assert.equal(JSON.parse(await page.evaluate(() => localStorage.getItem('whq-personal-resume-v1'))).summary, '这是我在当前页面直接修改后的个人简介。');
    await page.evaluate(() => show('ai'));
    await page.locator('#ai-ask textarea[name="prompt"]').fill('/简历');
    await page.locator('#ai-ask .send-btn').click();
    assert.equal(await page.locator('#ai-resume-dialog').evaluate((el) => el.open && el.parentElement.id === 'agent-stage'), true);
    await page.locator('#ai-resume-new-section').click();
    await page.locator('.resume-proposal[data-structured="true"] textarea').first().fill('北京四方小仓科技有限公司 Linker｜实习生\n2026.09 — 至今｜北京\n库存风险工作台（2026.09 — 2026.10）\n- 完成 CSV 字段映射和规则诊断；实际库存未修改。');
    await page.locator('.resume-proposal[data-structured="true"] textarea').last().fill('CSV 字段映射、规则型库存风险。');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#ai-ask textarea[name="prompt"]').fill('/简历');
    await page.locator('#ai-ask .send-btn').click();
    assert.match(await page.locator('.resume-proposal[data-structured="true"] textarea').first().inputValue(), /库存风险工作台/);
    await page.locator('#ai-resume-apply').click();
    const revised = JSON.parse(await page.evaluate(() => localStorage.getItem('whq-personal-resume-v1')));
    assert.match(revised.experience, /北京四方小仓科技有限公司/);
    assert.doesNotMatch(revised.experience, /库存风险工作台（2026\.09/);
    assert.doesNotMatch(revised.skills, /开发者申请与 OAuth 核对/);
    assert.equal(await page.locator('#resume-experience-imported').isVisible(), true);
    assert.match(await page.locator('#resume-ai-experience').textContent(), /库存风险工作台/);
    assert.match(await page.locator('#resume-ai-skills').textContent(), /CSV 字段映射/);
    assert.equal(await page.locator('#resume-ai-experience [data-resume-addition-action="remove"]').count(), 1);
    page.once('dialog', (dialog) => dialog.accept());
    await page.locator('#resume-ai-experience [data-resume-addition-action="remove"]').click();
    assert.doesNotMatch(await page.locator('#resume-ai-experience').textContent(), /库存风险工作台/);
    assert.match(await page.locator('#resume-experience-imported').textContent(), /参与社交内容发布平台接入/);
    await page.evaluate(() => {
      const current = JSON.parse(localStorage.getItem('whq-personal-resume-v1'));
      current.experience = '北京四方小仓科技有限公司 Linker｜实习生\n2026.09 — 至今｜北京\n社交内容发布平台接入（2026.10 记录）\n- 核对授权范围\n其他经历\n北京四方小仓科技有限公司 Linker｜实习生\n2026.09 — 至今｜北京\n库存风险工作台（2026.09 — 2026.10）\n- 完成字段映射\n其他经历\n原始经历：负责平台接入';
      current.skills += '\n开发者申请与 OAuth 核对、本机媒体地址限制排查、CSV 字段映射、规则型库存风险、模拟操作与真实数据隔离。';
      localStorage.setItem('whq-personal-resume-v1', JSON.stringify(current));
      localStorage.removeItem('whq-resume-legacy-ai-migrated-v1');
      renderResume();
    });
    const migrated = JSON.parse(await page.evaluate(() => localStorage.getItem('whq-personal-resume-v1')));
    assert.equal(migrated.experience, '原始经历：负责平台接入');
    assert.equal(await page.locator('#resume-ai-experience .resume-ai-entry').count(), 2);
    assert.equal(await page.locator('#resume-ai-experience .resume-company-head h3').count(), 1);
    assert.equal(await page.locator('#resume-ai-skills .resume-ai-entry').count(), 2);
    const grouped = await page.evaluate(() => {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = formatImportedExperience('示例有限公司｜实习生\n2026.09 — 至今\n项目 A（2026.09）\n- 第一项\n其他经历\n示例有限公司｜实习生\n2026.09 — 至今\n项目 B（2026.10）\n- 第二项');
      return { companies:wrapper.querySelectorAll('.resume-company').length, projects:wrapper.querySelectorAll('.resume-company-project').length };
    });
    assert.deepEqual(grouped, { companies:1, projects:2 });
    assert.deepEqual(errors, []);
    console.log('Resume assist browser flow passed (desktop, mobile, print, edit, remove).');
    await context.close();
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
