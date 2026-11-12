const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {pathToFileURL} = require('node:url');
let chromium;
try { ({chromium} = require('playwright-core')); }
catch { ({chromium} = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

async function main() {
  const browser = await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  try {
    const context = await browser.newContext({acceptDownloads:true});
    const page = await context.newPage();
    const errors=[];
    page.on('pageerror', error=>errors.push(error.message));
    const key='whq-personal-logs-v1';
    await page.addInitScript(() => {
      if (location.protocol==='file:') {
        localStorage.setItem('whq-personal-logs-v1','[{"id":"old-file-only","title":"文件入口旧记录"}]');
        localStorage.setItem('whq-personal-ai-access-v1','{"local":"none"}');
      }
    });
    let state={revision:12,data:{
      [key]:'[{"id":"central","title":"统一资料","date":"2026-11-03","time":"09:00","end":"10:00","source":"user","workspace":"personal"}]',
      'whq-personal-profile-v1':'{"name":"统一用户"}',
      'whq-personal-resume-v1':'{"name":"统一用户"}',
      'whq-recent-work-2026-10-27-v1':'1', 'whq-resume-legacy-ai-migrated-v1':'1'
    }};
    await page.route('**/*', async route=>{
      const url=new URL(route.request().url());
      if (url.protocol==='file:') return route.continue();
      const json=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
      const asset=url.pathname==='/'?'index.html':url.pathname.slice(1);
      if (['index.html','personal_sync.js','resume_template.js','intern_summaries.js','ui-shell.css','ui-calendar.css','ui-agent.css','ui-pages.css'].includes(asset)) {
        const file=path.join(__dirname,asset);
        if (!fs.existsSync(file)) return json({},404);
        return route.fulfill({contentType:asset.endsWith('.js')?'text/javascript':asset.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(file)});
      }
      if (url.pathname==='/api/personal-state') return json(state);
      if (url.pathname==='/api/personal-state/save') {
        const body=route.request().postDataJSON();
        if (body.base_revision!==state.revision) return json({snapshot:state,error:'conflict'},409);
        state={revision:state.revision+1,data:body.data};return json(state);
      }
      // No external requests, model requests, or real state mutations.
      return json({error:'disabled'},404);
    });
    const entry=pathToFileURL(path.join(__dirname,'index.html')).href;
    await page.goto(entry,{waitUntil:'domcontentloaded'}).catch(error=>{
      if (!/interrupted|ERR_ABORTED/.test(error.message)) throw error;
    });
    await page.waitForFunction(()=>location.origin==='http://127.0.0.1:8766' && document.getElementById('resume-name')?.textContent==='统一用户');
    assert.equal(new URL(page.url()).searchParams.has('legacy_file'),false,'migration path must be removed from the address bar');
    assert.equal(await page.evaluate(key=>JSON.parse(localStorage.getItem(key))[0].id,key),'central');
    assert.match(await page.locator('[aria-label="旧文件入口备份地址"]').inputValue(),/local-backup=1$/);
    await page.evaluate(()=>PersonalSync.flush());
    // Original file storage remains recoverable and never overwrites central data.
    await page.goto(entry+'?local-backup=1',{waitUntil:'domcontentloaded'});
    await page.waitForSelector('text=导出旧入口资料');
    assert.equal(await page.evaluate(()=>typeof show),'undefined');
    const downloaded=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出旧入口资料'}).click();
    const file=await (await downloaded).path();
    const backup=JSON.parse(fs.readFileSync(file,'utf8'));
    assert.equal(JSON.parse(backup.data[key])[0].id,'old-file-only');
    assert.equal(backup.data['whq-personal-ai-access-v1'],undefined);
    assert.equal(JSON.parse(state.data[key])[0].id,'central');
    assert.deepEqual(errors,[]);
    console.log('file entry redirects to shared platform; original file data remains exportable without permissions');
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
