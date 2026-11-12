const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless:true});
  try {
    for (const viewport of [{width:1665,height:920},{width:1280,height:800},{width:390,height:780}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      const calls = [];
      const tasks = [{id:'reminder-1',title:'核对结果',prompt:'检查今天的报告',kind:'reminder',repeat:'once',state:'needs_decision',next_run:'2026-10-29T10:00',running:false,last_run:{id:'run-1',status:'needs_decision',output:'检查今天的报告',error:'',progress:'',attempt:1,started_at:'2026-10-29T10:00',finished_at:'2026-10-29T10:00'}}];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/*', (route) => {
        const url = new URL(route.request().url());
        const asset = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        if (['index.html','intern_summaries.js','resume_template.js','ui-shell.css','ui-calendar.css','ui-agent.css','ui-pages.css'].includes(asset)) return route.fulfill({status:200,contentType:asset.endsWith('.js')?'text/javascript':asset.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,asset))});
        if (asset === 'personal_sync.js') return route.fulfill({status:200,contentType:'text/javascript',body:''});
        if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:'{"ok":false}'});
        if (url.pathname === '/api/tasks') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({tasks})});
        if (url.pathname === '/api/tasks/create') {
          const body = JSON.parse(route.request().postData()); calls.push({action:'create',body});
          tasks.unshift({id:'new-task',title:body.title,prompt:body.prompt,kind:body.kind,repeat:body.repeat,state:'active',next_run:body.run_at,running:false,last_run:null});
          return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(tasks[0])});
        }
        if (url.pathname === '/api/tasks/update') {
          const body = JSON.parse(route.request().postData()); calls.push({action:'update',body});
          Object.assign(tasks.find((item) => item.id === body.id),{title:body.title,prompt:body.prompt,kind:body.kind,repeat:body.repeat,next_run:body.run_at});
          return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(tasks.find((item) => item.id === body.id))});
        }
        if (url.pathname === '/api/tasks/action') {
          const body = JSON.parse(route.request().postData()); calls.push(body);
          const task = tasks.find((item) => item.id === body.id);
          task.state = body.action === 'complete' ? 'done' : body.action === 'run_now' ? 'active' : body.action === 'pause' ? 'paused' : 'active';
          if (body.action === 'complete') task.next_run = '';
          return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(task)});
        }
        if (url.pathname === '/api/ask') {
          const request = JSON.parse(route.request().postData());
          const interrupted = request.messages?.at(-1)?.content === '断线任务';
          return route.fulfill({status:200,contentType:'text/event-stream',body:interrupted
            ? 'event: progress_checkpoint\ndata: {"id":"progress12345678901234567890"}\n\n'
            : 'event: text\ndata: {"delta":"已继续"}\n\nevent: done\ndata: {"model":"mock"}\n\n'});
        }
        return route.fulfill({status:404,body:''});
      });
      await page.addInitScript(() => {
        localStorage.setItem('whq-recent-work-2026-10-27-v1','1');
        localStorage.setItem('whq-personal-ai-runs-v1',JSON.stringify([{id:'old-task',at:'2026-10-29T09:00:00',prompt:'继续查资料',text:'',thinking:'',tools:[],records:[],state:'paused',phase:'paused',checkpointId:'checkpoint12345678901234567890',browserAccess:'none',localAccess:'none',autoContinue:false}]));
      });
      await page.goto('http://127.0.0.1:8767/',{waitUntil:'domcontentloaded'});
      await page.evaluate(() => show('tasks'));
      await page.waitForFunction(() => document.getElementById('task-needs').textContent.includes('核对结果'));
      assert.equal(await page.locator('#task-needs-count').textContent(),'1');
      assert.equal(await page.locator('#task-conversations-count').textContent(),'1');
      const layout = await page.evaluate(() => {
        const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
        return {attention:rect('.task-attention'), create:rect('.task-create'), planned:rect('.task-planned'), conversations:rect('.task-conversations'), overflow:document.documentElement.scrollWidth > innerWidth};
      });
      assert.equal(layout.overflow,false);
      assert.ok(layout.attention.top < layout.create.top);
      assert.ok(layout.conversations.top - layout.planned.bottom < 50);
      if (viewport.width > 960) assert.ok(layout.create.right < layout.planned.left);
      else assert.ok(layout.create.bottom < layout.planned.top);
      await page.waitForSelector('#task-reminder-dialog[open]');
      assert.match(await page.locator('#task-reminder-content').textContent(),/检查今天的报告/);
      await page.locator('#task-reminder-dialog button[value="dismiss"]').click();
      assert.equal(await page.locator('#task-needs .task-output').count(),0);
      if (process.env.TASK_LAYOUT_SCREENSHOTS) {
        await page.screenshot({path:path.join(process.env.TASK_LAYOUT_SCREENSHOTS,`tasks-${viewport.width}.png`),fullPage:true});
        await page.evaluate(() => document.documentElement.setAttribute('data-theme','night'));
        await page.waitForFunction(() => getComputedStyle(document.getElementById('task-notification-enable')).backgroundColor === 'rgb(25, 34, 52)');
        const nightButton = await page.locator('#task-notification-enable').evaluate((el) => ({color:getComputedStyle(el).backgroundColor, surface:getComputedStyle(el).getPropertyValue('--surface'), rootSurface:getComputedStyle(document.documentElement).getPropertyValue('--surface')}));
        assert.notEqual(nightButton.color,'rgb(255, 255, 255)',JSON.stringify(nightButton));
        await page.screenshot({path:path.join(process.env.TASK_LAYOUT_SCREENSHOTS,`tasks-${viewport.width}-night.png`),fullPage:true});
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      assert.match(await page.locator('#task-conversations').textContent(),/继续查资料/);
      await page.locator('#task-needs [data-task-action="complete"]').click();
      await page.waitForFunction(() => !document.getElementById('task-needs').textContent.includes('核对结果'));
      await page.locator('#task-create [name="title"]').fill('每日检查');
      await page.locator('#task-create [name="prompt"]').fill('汇总公开行业资讯');
      await page.locator('#task-create [name="kind"]').selectOption('analysis');
      await page.locator('#task-create [name="repeat"]').selectOption('daily');
      await page.locator('#task-create button[type="submit"]').click();
      await page.waitForFunction(() => document.getElementById('task-scheduled').textContent.includes('每日检查'));
      assert.equal(calls.find((item) => item.action === 'create').body.kind,'analysis');
      await page.locator('#task-scheduled [data-task-edit="new-task"]').click();
      await page.locator('#task-create [name="title"]').fill('更新后的检查');
      await page.locator('#task-create button[type="submit"]').click();
      await page.waitForFunction(() => document.getElementById('task-scheduled').textContent.includes('更新后的检查'));
      assert.equal(calls.find((item) => item.action === 'update').body.id,'new-task');
      await page.locator('#task-conversations [data-chat-task]').click();
      await page.waitForFunction(() => aiRuns.find((run) => run.id === 'old-task').state === 'done');
      assert.equal(await page.locator('#ai').evaluate((el) => el.classList.contains('active')),true);
      await page.locator('#ai-ask [name="prompt"]').fill('断线任务');
      await page.locator('#ai-ask .send-btn').click();
      await page.waitForFunction(() => aiRuns.at(-1).state === 'paused');
      await page.evaluate(() => show('tasks'));
      await page.waitForFunction(() => document.getElementById('task-conversations').textContent.includes('断线任务'));
      assert.deepEqual(errors,[]);
      await page.close();
    }
    console.log('agent task UI OK');
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode=1; });
