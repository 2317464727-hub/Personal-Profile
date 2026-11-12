const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
let chromium;
try { ({chromium} = require('playwright-core')); }
catch { ({chromium} = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  try {
    for (const viewport of [{width:1280,height:800},{width:390,height:780}]) {
      const page = await browser.newPage({viewport});
      const errors = [], calls = [];
      const task = {id:'task-1',title:'按周历优化经历',prompt:'检查近期工作，给出有来源的经历草稿',kind:'analysis',repeat:'weekly',state:'needs_decision',running:false,next_run:'2026-11-10T09:00',
        grants:{logs:true,resume:true,files:[],consent:true},last_run:{id:'run-1',status:'needs_decision',output:'草稿待核对',sources:[{id:'周历:record-1',label:'记录一'}],drafts:[{id:'draft-1',kind:'resume',target:'experience',state:'pending'}]}};
      let tasks = [task], conflict = false;
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('dialog', (dialog) => dialog.accept());
      await page.addInitScript(() => {
        localStorage.setItem('whq-recent-work-2026-10-27-v1','1');
        window.syncCalls = 0; window.reloadCalls = 0;
        window.PersonalSync = {ready:Promise.resolve(),flush:async()=>{window.syncCalls++;if(window.failSync)throw new Error('资料存在冲突');return true;},reloadFromServer:async()=>{window.reloadCalls++;}};
      });
      await page.route('**/*', (route) => {
        const url = new URL(route.request().url());
        const asset = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        if (['index.html','intern_summaries.js','resume_template.js'].includes(asset)) return route.fulfill({status:200,contentType:asset.endsWith('.js')?'text/javascript':'text/html',body:fs.readFileSync(path.join(__dirname,asset))});
        if (asset === 'personal_sync.js') return route.fulfill({status:200,contentType:'text/javascript',body:''});
        const json = (body, status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
        if (url.pathname === '/api/health') return json({ok:false});
        if (url.pathname === '/api/tasks') return json({tasks});
        if (url.pathname.startsWith('/api/tasks/')) {
          const body = JSON.parse(route.request().postData() || '{}');
          calls.push({path:url.pathname,body});
          if (url.pathname === '/api/tasks/create') { tasks.push({...body,id:'created',state:'active',next_run:body.run_at,last_run:null});return json(tasks.at(-1)); }
          if (url.pathname === '/api/tasks/update') { Object.assign(tasks.find(t=>t.id===body.id),body);return json({ok:true}); }
          if (url.pathname === '/api/tasks/draft/preview') return conflict ? json({error:'原内容已改变，请重新生成草稿'},409) : json({preview_id:'preview-1',kind:'resume',label:'实习 / 工作经历',before:'旧的经历',after:'<img src=x onerror=alert(1)>\n新的、待核对的经历'});
          if (url.pathname === '/api/tasks/draft/apply') { task.last_run.drafts[0].state='applied';task.last_run.drafts[0].change_id='change-1';return json({kind:'resume',change_id:'change-1'}); }
          if (url.pathname === '/api/tasks/draft/undo') { task.last_run.drafts[0].state='undone';return json({kind:'resume',change_id:'change-1'}); }
        }
        return route.fulfill({status:404,body:''});
      });
      await page.goto('http://127.0.0.1:8767/',{waitUntil:'domcontentloaded'});
      await page.waitForFunction(()=>typeof show==='function');
      await page.evaluate(()=>show('tasks'));
      await page.waitForSelector('[data-task-draft="draft-1"]');
      assert.equal(await page.locator('#task-source-settings').isVisible(),false);
      const form = page.locator('#task-create');
      await form.locator('[name="title"]').fill('每周写经历');
      await form.locator('[name="prompt"]').fill('按授权资料提出草稿');
      await form.locator('[name="kind"]').selectOption('analysis');
      await form.locator('[name="grant_logs"]').check();
      await form.locator('[name="grant_resume"]').check();
      await form.locator('[name="grant_files"]').fill('C:\\Users\\demo\\Desktop\\note.txt');
      await form.locator('button[type="submit"]').click();
      await page.waitForFunction(()=>document.getElementById('task-status').textContent.includes('请先勾选'));
      assert.equal(calls.filter(c=>c.path.endsWith('/create')).length,0);
      await form.locator('[name="grant_consent"]').check();
      await page.evaluate(()=>{window.failSync=true;});
      await form.locator('button[type="submit"]').click();
      await page.waitForFunction(()=>document.getElementById('task-status').textContent.includes('资料存在冲突'));
      assert.equal(calls.filter(c=>c.path.endsWith('/create')).length,0);
      await page.evaluate(()=>{window.failSync=false;});
      await form.locator('button[type="submit"]').click();
      await page.waitForSelector('[data-task-edit="created"]');
      assert.deepEqual(calls.find(c=>c.path.endsWith('/create')).body.grants,{logs:true,resume:true,files:['C:\\Users\\demo\\Desktop\\note.txt'],consent:true});
      await page.locator('[data-task-edit="created"]').click();
      assert.equal(await form.locator('[name="grant_logs"]').isChecked(),true);
      assert.equal(await form.locator('[name="grant_consent"]').isChecked(),true);
      await form.locator('[name="grant_logs"]').uncheck();
      await form.locator('[name="grant_resume"]').uncheck();
      await form.locator('[name="grant_files"]').fill('');
      await form.locator('[name="grant_consent"]').uncheck();
      await form.locator('button[type="submit"]').click();
      await page.waitForFunction(()=>document.getElementById('task-status').textContent.includes('修改已保存'));
      assert.deepEqual(calls.find(c=>c.path.endsWith('/update')).body.grants,{logs:false,resume:false,files:[],consent:false});
      await page.locator('.task-sources summary').click();
      assert.match(await page.locator('.task-sources').textContent(),/周历:record-1/);
      await page.locator('[data-task-draft="draft-1"]').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent.includes('尚未修改'));
      assert.equal(calls.filter(c=>c.path.endsWith('/apply')).length,0);
      assert.equal(await page.locator('#task-draft-after img').count(),0);
      assert.match(await page.locator('#task-draft-after').textContent(),/<img/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth),true);
      await page.locator('#task-draft-close').click();
      assert.equal(calls.filter(c=>c.path.endsWith('/apply')).length,0);
      conflict = true;
      await page.locator('[data-task-draft="draft-1"]').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent.includes('原内容已改变'));
      assert.equal(await page.locator('#task-draft-apply').isDisabled(),true);
      await page.locator('#task-draft-close').click();
      conflict = false;
      await page.locator('[data-task-draft="draft-1"]').click();
      await page.waitForFunction(()=>!document.getElementById('task-draft-apply').disabled);
      await page.locator('#task-draft-apply').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent.includes('已写入'));
      assert.deepEqual(calls.find(c=>c.path.endsWith('/apply')).body,{preview_id:'preview-1',confirm:true});
      assert.equal(calls.filter(c=>c.path.endsWith('/apply')).length,1);
      assert.equal(await page.evaluate(()=>window.reloadCalls),1);
      await page.locator('#task-draft-undo').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent.includes('已撤销'));
      assert.deepEqual(calls.find(c=>c.path.endsWith('/undo')).body,{change_id:'change-1',confirm:true});
      assert.equal(await page.evaluate(()=>window.reloadCalls),2);
      assert.deepEqual(errors,[]);
      await page.close();
    }
    console.log('task materials and confirmed draft UI OK (desktop + mobile)');
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
