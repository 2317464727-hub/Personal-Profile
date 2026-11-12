const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
let chromium;
try { ({chromium} = require('playwright-core')); }
catch { ({chromium} = require(path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'))); }

const PROFILE = 'whq-personal-profile-v1';
const LOGS = 'whq-personal-logs-v1';
const script = fs.readFileSync(path.join(__dirname, 'personal_sync.js'), 'utf8');
const html = '<!doctype html><html><head><meta charset="utf-8"></head><body><section id="tasks"><div class="task-workspace"></div></section>' +
  '<script src="/personal_sync.js"></script><script>PersonalSync.ready.then(() => {window.appInitialProfile = localStorage.getItem("whq-personal-profile-v1"); window.appStarted = true;});</script></body></html>';

async function fixture(browser, initial, local = {}, offline = false, shared = null) {
  const context = browser.newContext ? await browser.newContext({viewport:{width:390,height:780}, acceptDownloads:true}) : browser;
  const page = await context.newPage();
  const control = shared || {snapshot:structuredClone(initial), saves:[], restores:[], offline, previous:null};
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.addInitScript(values => Object.entries(values).forEach(([key,value]) => localStorage.setItem(key,value)), local);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({contentType:'text/html', body:html});
    if (url.pathname === '/personal_sync.js') return route.fulfill({contentType:'text/javascript', body:script});
    if (control.offline) return route.fulfill({status:503, contentType:'application/json', body:'{"error":"offline"}'});
    const reply = (data, status = 200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(data)});
    if (url.pathname === '/api/personal-state') return reply(control.snapshot);
    if (url.pathname === '/api/personal-state/backup') return reply({format:'whq-personal-backup',version:1,...control.snapshot});
    if (url.pathname === '/api/personal-state/save' || url.pathname === '/api/personal-state/restore') {
      const body = route.request().postDataJSON();
      const restore = url.pathname.endsWith('/restore');
      (restore ? control.restores : control.saves).push(body);
      if (control.delayNextSave) { control.delayNextSave = false; await new Promise(resolve => setTimeout(resolve, 80)); }
      if (body.base_revision !== control.snapshot.revision) return reply({error:'conflict',snapshot:control.snapshot},409);
      if (restore) control.previous = structuredClone(control.snapshot);
      control.snapshot = {revision:control.snapshot.revision + 1, data:restore ? body.backup.data : body.data, updated_at:'2026-11-03T12:00:00Z'};
      return reply(control.snapshot);
    }
    return reply({error:'unknown'},404);
  });
  await page.goto('http://127.0.0.1:18766/', {waitUntil:'domcontentloaded'});
  await page.waitForFunction(() => window.appStarted);
  return {page,control,errors};
}

async function main() {
  const browser = await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless:true});
  try {
    // Fresh browser loads persisted data before the application starts, but no permissions.
    let item = await fixture(browser, {revision:3,data:{[PROFILE]:'{"name":"服务资料"}'}}, {'whq-personal-ai-access-v1':'{"local":"none"}'});
    assert.equal(await item.page.evaluate(() => appInitialProfile), '{"name":"服务资料"}');
    assert.equal(await item.page.evaluate(() => localStorage.getItem('whq-personal-ai-access-v1')), '{"local":"none"}');
    await item.page.evaluate(async () => {
      localStorage.setItem('whq-personal-profile-v1','{"name":"更新资料"}');
      await PersonalSync.flush();
    });
    assert.equal(item.control.snapshot.data[PROFILE], '{"name":"更新资料"}');
    assert.equal(item.control.snapshot.data['whq-personal-ai-access-v1'], undefined);
    item.control.delayNextSave = true;
    await item.page.evaluate(async () => {
      localStorage.setItem('whq-personal-profile-v1','{"name":"发送中"}');
      setTimeout(() => localStorage.setItem('whq-personal-profile-v1','{"name":"发送时继续编辑"}'), 20);
      await PersonalSync.flush();
    });
    assert.equal(item.control.snapshot.data[PROFILE], '{"name":"发送时继续编辑"}');
    // A second writer wins first; this page must preserve its own edit and stop.
    item.control.snapshot = {revision:9,data:{[PROFILE]:'{"name":"其他页面"}'}};
    const conflict = await item.page.evaluate(async () => {
      localStorage.setItem('whq-personal-profile-v1','{"name":"当前页面"}');
      try { await PersonalSync.flush(); } catch (error) { return PersonalSync.hasConflict; }
    });
    assert.equal(conflict, true);
    assert.equal(item.control.snapshot.data[PROFILE], '{"name":"其他页面"}');
    assert.equal(await item.page.evaluate(() => localStorage.getItem('whq-personal-profile-v1')), '{"name":"当前页面"}');
    await item.page.evaluate(() => {window.reloadEvents = 0; window.addEventListener('personal-state-loaded', () => reloadEvents++);});
    const download = item.page.waitForEvent('download');
    await item.page.locator('[data-sync-remote]').click();
    assert.match((await download).suggestedFilename(), /切换前浏览器资料/);
    await item.page.waitForFunction(() => !PersonalSync.hasConflict);
    assert.equal(await item.page.evaluate(() => localStorage.getItem('whq-personal-profile-v1')), '{"name":"其他页面"}');
    assert.equal(await item.page.evaluate(() => reloadEvents), 1);
    item.control.snapshot = {revision:10,data:{[PROFILE]:'{"name":"确认后的草稿"}'}};
    await item.page.evaluate(() => PersonalSync.reloadFromServer());
    assert.equal(await item.page.evaluate(() => reloadEvents), 2);
    assert.equal(await item.page.evaluate(() => localStorage.getItem('whq-personal-profile-v1')), '{"name":"确认后的草稿"}');
    await item.page.evaluate(() => {window.canReloadPersonalState = () => false;});
    assert.match(await item.page.evaluate(async () => {try {await PersonalSync.reloadFromServer();} catch (error) {return error.message;}}), /AI 正在运行/);
    assert.deepEqual(item.errors, []);
    await item.page.close({runBeforeUnload:false});

    // Untracked legacy origins adopt the service, retaining the complete old copy.
    item = await fixture(browser, {revision:4,data:{[PROFILE]:'{"name":"服务版"}'}}, {[PROFILE]:'{"name":"浏览器版"}'});
    assert.equal(await item.page.evaluate(() => PersonalSync.hasConflict), false);
    assert.equal(await item.page.evaluate(() => appInitialProfile), '{"name":"服务版"}');
    assert.equal(await item.page.evaluate(() => JSON.parse(localStorage.getItem('whq-personal-sync-recovery-v1')).data['whq-personal-profile-v1']), '{"name":"浏览器版"}');
    assert.equal(item.control.saves.length, 0);
    assert.equal(await item.page.locator('[data-sync-recovery]').isVisible(), true);
    // A genuine concurrent edit still requires a choice; restore keeps a backup.
    item.control.snapshot = {revision:5,data:{[PROFILE]:'{"name":"另一个服务版"}'}};
    await item.page.evaluate(async () => {
      localStorage.setItem('whq-personal-profile-v1', '{"name":"浏览器版"}');
      await PersonalSync.flush().catch(() => {});
    });
    assert.equal(await item.page.evaluate(() => PersonalSync.hasConflict), true);
    await item.page.locator('[data-sync-local]').click();
    await item.page.waitForFunction(() => !PersonalSync.hasConflict);
    assert.equal(item.control.restores[0].confirm, true);
    assert.equal(item.control.previous.data[PROFILE], '{"name":"另一个服务版"}');
    assert.equal(item.control.snapshot.data[PROFILE], '{"name":"浏览器版"}');
    assert.equal(await item.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(item.errors, []);
    await item.page.close({runBeforeUnload:false});

    // Two independent browser profiles share one store, including additions,
    // deletions, background changes and edits made while disconnected.
    const firstLog = {id:'existing',title:'原记录',date:'2026-11-03'};
    item = await fixture(browser, {revision:12,data:{[LOGS]:JSON.stringify([firstLog]),[PROFILE]:'{"name":"测试","role":"原岗位"}'}});
    const other = await fixture(browser, null, {}, false, item.control);
    await Promise.all([item.page.evaluate(async () => {
      const key='whq-personal-logs-v1';
      localStorage.setItem(key, JSON.stringify([...JSON.parse(localStorage.getItem(key)),{id:'left',title:'窗口一'}]));
      await PersonalSync.flush();
    }), other.page.evaluate(async () => {
      const key='whq-personal-logs-v1';
      localStorage.setItem(key, JSON.stringify([...JSON.parse(localStorage.getItem(key)),{id:'right',title:'窗口二'}]));
      await PersonalSync.flush();
    })]);
    assert.deepEqual(JSON.parse(item.control.snapshot.data[LOGS]).map(x=>x.id).sort(), ['existing','left','right']);
    await Promise.all([item.page.evaluate(()=>PersonalSync.refresh()),other.page.evaluate(()=>PersonalSync.refresh())]);
    await item.page.evaluate(async () => {
      const key='whq-personal-logs-v1';localStorage.setItem(key, JSON.stringify(JSON.parse(localStorage.getItem(key)).filter(x=>x.id!=='existing')));
      await PersonalSync.flush();
    });
    await other.page.evaluate(async () => {
      const key='whq-personal-logs-v1';localStorage.setItem(key, JSON.stringify([...JSON.parse(localStorage.getItem(key)),{id:'later',title:'并行新增'}]));
      await PersonalSync.flush();
    });
    assert.deepEqual(JSON.parse(item.control.snapshot.data[LOGS]).map(x=>x.id).sort(), ['later','left','right']);
    await item.page.evaluate(()=>PersonalSync.refresh());
    assert.equal(await item.page.evaluate(()=>JSON.parse(localStorage.getItem('whq-personal-logs-v1')).length), 3);
    // Automatic polling imports external writes without a refresh button.
    item.control.snapshot = {...item.control.snapshot,revision:item.control.snapshot.revision+1,data:{...item.control.snapshot.data,[PROFILE]:'{"name":"测试","role":"自动同步岗位"}'}};
    await item.page.waitForFunction(()=>JSON.parse(localStorage.getItem('whq-personal-profile-v1')).role==='自动同步岗位');
    // Defer background hydration while the app is editing, then catch up.
    await item.page.evaluate(()=>{window.canRefreshPersonalState=()=>false;});
    item.control.snapshot = {...item.control.snapshot,revision:item.control.snapshot.revision+1,data:{...item.control.snapshot.data,[PROFILE]:'{"name":"测试","role":"编辑结束后更新"}'}};
    await item.page.evaluate(()=>PersonalSync.refresh());
    assert.equal(await item.page.evaluate(()=>JSON.parse(localStorage.getItem('whq-personal-profile-v1')).role), '自动同步岗位');
    await item.page.evaluate(async()=>{window.canRefreshPersonalState=()=>true;await PersonalSync.refresh();});
    assert.equal(await item.page.evaluate(()=>JSON.parse(localStorage.getItem('whq-personal-profile-v1')).role), '编辑结束后更新');
    // Reload with unsent work must use persisted baseline hashes to merge.
    await item.page.evaluate(()=>{localStorage.setItem('whq-personal-profile-v1','{"name":"离线姓名","role":"编辑结束后更新"}');});
    item.control.snapshot = {...item.control.snapshot,revision:item.control.snapshot.revision+1,data:{...item.control.snapshot.data,[PROFILE]:'{"name":"测试","role":"远端新岗位"}'}};
    await item.page.reload({waitUntil:'domcontentloaded'});
    await item.page.waitForFunction(()=>window.appStarted);
    assert.equal(await item.page.evaluate(()=>PersonalSync.hasConflict),false);
    assert.deepEqual(JSON.parse(item.control.snapshot.data[PROFILE]), {name:'离线姓名',role:'远端新岗位'});
    assert.deepEqual(item.errors, []);assert.deepEqual(other.errors, []);
    await other.page.close({runBeforeUnload:false});await item.page.close({runBeforeUnload:false});

    // Old standalone browsers keep all their unique records on first migration.
    item = await fixture(browser, {revision:12,data:{[LOGS]:JSON.stringify([firstLog])}}, {[LOGS]:JSON.stringify([{id:'legacy',title:'旧入口独有记录'}])});
    assert.deepEqual(JSON.parse(item.control.snapshot.data[LOGS]).map(x=>x.id), ['existing','legacy']);
    assert.equal(await item.page.evaluate(()=>PersonalSync.hasConflict),false);
    const sibling = await fixture(item.page.context(), null, {}, false, item.control);
    await item.page.evaluate(async()=>{
      const key='whq-personal-logs-v1';localStorage.setItem(key,JSON.stringify([...JSON.parse(localStorage.getItem(key)),{id:'same-origin',title:'同源标签页同步'}]));
      await PersonalSync.flush();
    });
    await sibling.page.waitForFunction(()=>PersonalSync.revision>=14);
    assert.equal(await sibling.page.evaluate(()=>JSON.parse(localStorage.getItem('whq-personal-logs-v1')).length),3);
    assert.deepEqual(item.errors, []);assert.deepEqual(sibling.errors, []);
    await sibling.page.close({runBeforeUnload:false});await item.page.close({runBeforeUnload:false});

    // Offline startup remains usable and a retry migrates retained browser data.
    item = await fixture(browser, {revision:0,data:{}}, {[PROFILE]:'{"name":"离线修改"}'}, true);
    assert.equal(await item.page.evaluate(() => appInitialProfile), '{"name":"离线修改"}');
    assert.match(await item.page.locator('[data-sync-status]').textContent(), /尚未同步/);
    item.control.offline = false;
    await item.page.evaluate(() => PersonalSync.flush());
    assert.equal(item.control.snapshot.data[PROFILE], '{"name":"离线修改"}');
    // A new/removed server database must not erase a previously synced browser.
    item.control.snapshot = {revision:0,data:{}};
    await item.page.reload({waitUntil:'domcontentloaded'});
    await item.page.waitForFunction(() => typeof appInitialProfile !== 'undefined');
    assert.equal(await item.page.evaluate(() => appInitialProfile), '{"name":"离线修改"}');
    assert.equal(item.control.snapshot.data[PROFILE], '{"name":"离线修改"}');
    assert.deepEqual(item.errors, []);
    await item.page.close({runBeforeUnload:false});
    console.log('personal storage UI migration, conflict, offline and permission checks OK');
  } finally { await browser.close(); }
}
main().catch(error => {console.error(error);process.exitCode = 1;});
