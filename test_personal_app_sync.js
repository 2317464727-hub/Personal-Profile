const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
let chromium;
try { ({chromium} = require('playwright-core')); }
catch { ({chromium} = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

const resumeKey = 'whq-personal-resume-v1';
const logKey = 'whq-personal-logs-v1';
const clone = value => JSON.parse(JSON.stringify(value));

async function main() {
  const browser = await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  const imageDir = path.join(__dirname, '.test-tmp');
  fs.mkdirSync(imageDir, {recursive:true});
  try {
    for (const viewport of [{width:1280,height:800},{width:390,height:780}]) {
      const page = await browser.newPage({viewport});
      const errors = [], calls = [];
      const originalExperience = '示例科技｜研发实习生\n2026.07—2026.10\n- 按记录整理需求，完成测试核对。';
      const revisedExperience = '示例科技｜研发实习生\n2026.07—2026.10\n- 基于实际工作记录梳理需求与测试过程，明确已验证结果。';
      let remote = {revision:7, updated_at:'2026-11-03T02:00:00Z',data:{
        [resumeKey]:JSON.stringify({name:'合成测试用户',role:'研发实习生',experience:originalExperience,projects:'合成项目原文',skills:'历史技能已写入',education:'示例大学',phone:'合成联系方式'}),
        [logKey]:JSON.stringify([{id:'synthetic-log-1',title:'合成工作记录',body:'核对测试结果，仅用于自动化测试',date:'2026-11-02',time:'09:00',end:'10:00',workspace:'personal',source:'user',attachments:[]}]),
        'whq-personal-profile-v1':JSON.stringify({name:'合成测试用户',role:'研发实习生',focusItems:[]}),
        'whq-recent-work-2026-10-27-v1':'1','whq-resume-legacy-ai-migrated-v1':'1',
      }};
      const task = {id:'task-integrated',title:'每周复盘并完善简历',prompt:'根据授权的周历和简历，提出具体草稿',kind:'analysis',repeat:'weekly',state:'needs_decision',running:false,next_run:'2026-11-10T09:00',grants:{logs:true,resume:true,files:[],consent:true},
        last_run:{id:'run-current',status:'needs_decision',output:'已查阅资料，请核对经历修改草稿。',finished_at:'2026-11-03T10:00',sources:[{id:'周历:synthetic-log-1',label:'合成工作记录'}],drafts:[{id:'draft-current',kind:'resume',target:'experience',state:'pending'}]},
        draft_history:[{id:'run-previous',finished_at:'2026-10-27T10:00',drafts:[{id:'draft-previous',kind:'resume',target:'projects',state:'pending'},{id:'draft-historic-applied',kind:'resume',target:'skills',state:'applied',change_id:'change-historic'}]}]};
      let firstStateRead = true, releaseInitial;
      const initialGate = new Promise(resolve=>{releaseInitial=resolve;});
      page.on('pageerror', error=>errors.push(error.message));
      page.on('dialog', dialog=>dialog.accept());
      await page.addInitScript(() => {
        window.hydrationEvents=0;
        window.addEventListener('personal-state-loaded',()=>{window.hydrationEvents++;});
      });
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        const asset = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        if (['index.html','personal_sync.js','intern_summaries.js','resume_template.js'].includes(asset)) return route.fulfill({status:200,contentType:asset.endsWith('.js')?'text/javascript':'text/html',body:fs.readFileSync(path.join(__dirname,asset))});
        const json = (body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
        if (url.pathname === '/api/personal-state') {
          if (firstStateRead) { firstStateRead=false;await initialGate; }
          return json(clone(remote));
        }
        if (url.pathname === '/api/personal-state/save') {
          const body=JSON.parse(route.request().postData());calls.push({path:url.pathname,body});
          if (body.base_revision !== remote.revision) return json({error:'版本已变化',snapshot:clone(remote)},409);
          if (JSON.stringify(remote.data)!==JSON.stringify(body.data)) remote={...remote,revision:remote.revision+1,data:clone(body.data)};
          return json(clone(remote));
        }
        if (url.pathname === '/api/health') return json({ok:false,model:'mock-no-network'});
        if (url.pathname === '/api/tasks') return json({tasks:[clone(task)]});
        if (url.pathname === '/api/tasks/draft/preview') {
          const body=JSON.parse(route.request().postData());calls.push({path:url.pathname,body});
          const current = body.draft_id === 'draft-current';
          return json({preview_id:current?'preview-current':'preview-previous',kind:'resume',label:current?'实习 / 工作经历':'项目经历',before:current?originalExperience:'合成项目原文',after:current?revisedExperience:'合成项目新草稿'});
        }
        if (url.pathname === '/api/tasks/draft/apply') {
          const body=JSON.parse(route.request().postData());calls.push({path:url.pathname,body});
          assert.equal(body.confirm,true);
          assert.equal(body.preview_id,'preview-current');
          const resume=JSON.parse(remote.data[resumeKey]);resume.experience=revisedExperience;
          remote={...remote,revision:remote.revision+1,data:{...remote.data,[resumeKey]:JSON.stringify(resume)}};
          Object.assign(task.last_run.drafts[0],{state:'applied',change_id:'change-current'});
          return json({kind:'resume',change_id:'change-current',state:clone(remote)});
        }
        if (url.pathname === '/api/tasks/draft/undo') {
          const body=JSON.parse(route.request().postData());calls.push({path:url.pathname,body});
          assert.equal(body.confirm,true);
          const resume=JSON.parse(remote.data[resumeKey]);
          if (body.change_id==='change-current') { resume.experience=originalExperience;task.last_run.drafts[0].state='undone'; }
          else { assert.equal(body.change_id,'change-historic');resume.skills='历史技能原文';task.draft_history[0].drafts[1].state='undone'; }
          remote={...remote,revision:remote.revision+1,data:{...remote.data,[resumeKey]:JSON.stringify(resume)}};
          return json({kind:'resume',change_id:body.change_id,state:clone(remote)});
        }
        if (url.pathname.startsWith('/api/intern-summary')) return json({enabled:false,records:[],logs_count:0,summaries:[]});
        // No live model calls, filesystem endpoints or external requests are forwarded.
        return json({error:'Test endpoint disabled'},404);
      });
      await page.goto('http://127.0.0.1:8767/',{waitUntil:'domcontentloaded'});
      assert.equal(await page.evaluate(()=>typeof show),'undefined','App must wait for remote hydration');
      assert.equal(await page.locator('#personal-app-script').count(),1);
      releaseInitial();
      await page.waitForFunction(()=>typeof show==='function' && document.getElementById('resume-name').textContent==='合成测试用户');
      assert.equal(await page.locator('#personal-app-script').count(),0);
      assert.equal(await page.evaluate(()=>PersonalSync.hasConflict),false);
      assert.match(await page.locator('#resume-experience-imported').textContent(),/按记录整理需求/);
      assert.match(await page.locator('#home-record-manage-list').textContent(),/合成工作记录/);
      assert.equal(JSON.parse(await page.evaluate(key=>localStorage.getItem(key),resumeKey)).name,'合成测试用户');
      await page.evaluate(async () => {
        const key='whq-personal-logs-v1';
        const logs=JSON.parse(localStorage.getItem(key));logs[0].body='本机编辑后的合成记录';
        localStorage.setItem(key,JSON.stringify(logs));
        await PersonalSync.flush();
      });
      assert.equal(JSON.parse(remote.data[logKey])[0].body,'本机编辑后的合成记录');
      assert.ok(calls.some(call=>call.path==='/api/personal-state/save'));
      assert.equal(await page.evaluate(()=>PersonalSync.revision),remote.revision);
      await page.evaluate(()=>show('tasks'));
      await page.waitForSelector('[data-task-draft="draft-current"]');
      await page.locator('[data-task-draft="draft-current"]').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent.includes('尚未修改'));
      assert.equal(calls.filter(call=>call.path.endsWith('/apply')).length,0);
      assert.equal(JSON.parse(remote.data[resumeKey]).experience,originalExperience);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
      await page.screenshot({path:path.join(imageDir,`personal-draft-${viewport.width}.png`)});
      await page.locator('#task-draft-apply').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent==='已写入，原内容已备份。');
      assert.equal(await page.evaluate(()=>window.hydrationEvents),1);
      assert.match(await page.locator('#resume-experience-imported').textContent(),/基于实际工作记录/);
      assert.equal(await page.locator('#task-draft-dialog').evaluate(el=>el.open),true);
      assert.equal(await page.locator('#task-draft-undo').isVisible(),true);
      assert.equal(await page.evaluate(()=>PersonalSync.revision),remote.revision);
      assert.equal(JSON.parse(remote.data[resumeKey]).phone,'合成联系方式');
      await page.locator('#task-draft-undo').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-status').textContent.includes('已撤销'));
      assert.equal(await page.evaluate(()=>window.hydrationEvents),2);
      assert.match(await page.locator('#resume-experience-imported').textContent(),/按记录整理需求/);
      await page.locator('#task-draft-close').click();
      await page.getByText('以往草稿与撤销记录',{exact:true}).click();
      await page.locator('[data-task-draft="draft-previous"]').click();
      await page.waitForFunction(()=>document.getElementById('task-draft-after').textContent==='合成项目新草稿');
      assert.deepEqual(calls.filter(call=>call.path.endsWith('/preview')).at(-1).body,{task_id:'task-integrated',run_id:'run-previous',draft_id:'draft-previous'});
      await page.locator('#task-draft-close').click();
      await page.getByText('以往草稿与撤销记录',{exact:true}).click();
      await page.locator('[data-task-draft-undo="change-historic"]').click();
      await page.waitForFunction(()=>document.getElementById('task-status').textContent.includes('已撤销'));
      assert.equal(await page.evaluate(()=>window.hydrationEvents),3);
      assert.match(await page.locator('#resume-skills-imported').textContent(),/历史技能原文/);
      assert.equal(calls.filter(call=>call.path.endsWith('/apply')).length,1);
      assert.equal(calls.filter(call=>call.path.endsWith('/undo')).length,2);
      // Polling must not replace an active editor or discard its draft when
      // another browser updates unrelated persisted records.
      await page.evaluate(()=>show('week'));
      await page.locator('#new-week-record').click();
      await page.locator('#week .log-form input[name="title"]').fill('尚未提交的标题');
      await page.locator('#week .log-form textarea[name="body"]').fill('正在编辑的画布正文');
      await page.evaluate(()=>PersonalSync.flush());
      const updatedResume=JSON.parse(remote.data[resumeKey]);updatedResume.name='另一个窗口修改的姓名';
      const updatedLogs=JSON.parse(remote.data[logKey]);updatedLogs.push({id:'another-window',title:'另一个窗口新增的记录',date:'2026-11-03',time:'10:00',end:'11:00',workspace:'personal',source:'user'});
      remote={...remote,revision:remote.revision+1,data:{...remote.data,[resumeKey]:JSON.stringify(updatedResume),[logKey]:JSON.stringify(updatedLogs)}};
      await page.evaluate(()=>PersonalSync.refresh());
      assert.equal(await page.locator('#resume-name').textContent(),'合成测试用户');
      assert.equal(await page.locator('#week .log-form textarea[name="body"]').inputValue(),'正在编辑的画布正文');
      await page.locator('#week .log-form textarea[name="body"]').blur();
      await page.evaluate(()=>PersonalSync.refresh());
      assert.equal(await page.locator('#resume-name').textContent(),'另一个窗口修改的姓名');
      assert.equal(await page.locator('#week .log-form textarea[name="body"]').inputValue(),'正在编辑的画布正文');
      assert.equal(await page.locator('#week .log-form input[name="title"]').inputValue(),'尚未提交的标题');
      assert.equal(await page.evaluate(()=>PersonalSync.hasConflict),false);
      assert.deepEqual(errors,[]);
      await page.close({runBeforeUnload:false});
    }
    console.log('integrated real personal sync + app hydration + historical drafts UI OK (desktop + mobile)');
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
