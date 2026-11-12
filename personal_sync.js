/* Explicit personal-data storage. Browser permissions never enter the backup. */
(() => {
  'use strict';
  if (window.personalFileEntry) return;
  const keys = [
    'whq-personal-profile-v1', 'whq-personal-resume-v1', 'whq-personal-logs-v1',
    'whq-personal-resume-photo-v1', 'whq-resume-work-additions-v1',
    'whq-resume-reviewed-sources-v1', 'whq-resume-pending-draft-v1',
    'whq-resume-advice-review-v1', 'whq-week-pending-v1',
    'whq-personal-ai-runs-v1', 'whq-personal-ai-keywords-v1',
    'whq-personal-ai-keywords-scoped-v1', 'whq-home-hidden-logs-v1',
    'whq-resume-legacy-ai-migrated-v1', 'whq-recent-work-2026-10-27-v1'
  ];
  const allowed = new Set(keys);
  const metaKey = 'whq-personal-sync-meta-v1';
  const recoveryKey = 'whq-personal-sync-recovery-v1';
  const logsKey = 'whq-personal-logs-v1';
  const scope = '包含个人资料、周历文字、简历及照片、草稿、AI 对话和关键词。不包含周历或画布的附件文件、定时任务、访问权限和密钥；附件请另行保留。';
  const nativeSet = Storage.prototype.setItem;
  const nativeRemove = Storage.prototype.removeItem;
  let revision = null, baseline = '', conflict = null, timer = null, saving = null;
  let baseMarks = {}, renderPending = false;
  let started = false, suppress = false, panel = null, badge = null;
  let message = '正在连接本机资料库…';
  const readLocal = () => Object.fromEntries(keys.flatMap(key => {
    const value = localStorage.getItem(key);
    return value === null ? [] : [[key, value]];
  }));
  const canonical = data => JSON.stringify(Object.keys(data).sort().map(key => [key, data[key]]));
  // Store a small comparison marker, not another full copy of private material.
  const fingerprint = data => {
    const text = canonical(data);
    let one = 2166136261, two = 5381;
    for (let i = 0; i < text.length; i++) {
      one = Math.imul(one ^ text.charCodeAt(i), 16777619);
      two = Math.imul(two, 33) ^ text.charCodeAt(i);
    }
    return `${text.length}:${one >>> 0}:${two >>> 0}`;
  };
  const hash = value => value === undefined ? 'absent' : fingerprint({value});
  const parse = value => { try { return JSON.parse(value); } catch (_) { return null; } };
  const indexed = value => {
    if (!Array.isArray(value) || value.some(item => !item || typeof item.id !== 'string' || !item.id)) return null;
    const map = Object.fromEntries(value.map(item => [item.id, item]));
    return Object.keys(map).length === value.length ? map : null;
  };
  function describe(data) {
    return Object.fromEntries(Object.entries(data).map(([key, value]) => {
      const node = {hash:hash(value)}, decoded = parse(value);
      if (key === logsKey && indexed(decoded)) node.items = Object.fromEntries(decoded.map(item => [item.id, hash(item)]));
      if (['whq-personal-profile-v1', 'whq-personal-resume-v1'].includes(key) && decoded && !Array.isArray(decoded)) {
        node.fields = Object.fromEntries(Object.entries(decoded).map(([field, text]) => [field, hash(text)]));
      }
      return [key, node];
    }));
  }
  // Three-way comparisons retain independent edits and propagate real deletions.
  // Persist only hashes, so restarting a browser need not duplicate private text.
  function merge(remote, local) {
    const result = {};
    function choose(before, left, right) {
      if (hash(left) === hash(right) || hash(right) === before) return left;
      if (hash(left) === before) return right;
      throw new Error('同一项资料在两个窗口中都被修改，请核对版本');
    }
    for (const key of new Set([...Object.keys(baseMarks), ...Object.keys(local), ...Object.keys(remote)])) {
      const base = baseMarks[key] || (key === logsKey ? {hash:'absent', items:{}} : {hash:'absent'});
      let value;
      try { value = choose(base.hash, local[key], remote[key]); }
      catch (error) {
        const left = parse(local[key]), right = parse(remote[key]);
        const maps = base.items ? [indexed(left), indexed(right)] : base.fields ? [left, right] : [];
        if (!maps[0] || !maps[1] || Array.isArray(maps[0]) || Array.isArray(maps[1])) throw error;
        const before = base.items || base.fields, combined = {};
        for (const field of new Set([...Object.keys(maps[1]), ...Object.keys(maps[0]), ...Object.keys(before)])) {
          const item = choose(Object.hasOwn(before, field) ? before[field] : 'absent',
            Object.hasOwn(maps[0], field) ? maps[0][field] : undefined,
            Object.hasOwn(maps[1], field) ? maps[1][field] : undefined);
          if (item !== undefined) Object.defineProperty(combined, field, {value:item, enumerable:true});
        }
        value = JSON.stringify(base.items ? Object.values(combined) : combined);
      }
      if (value !== undefined) result[key] = value;
    }
    return result;
  }
  function mark(snapshot) {
    revision = snapshot.revision;
    baseline = canonical(snapshot.data);
    baseMarks = describe(snapshot.data);
    nativeSet.call(localStorage, metaKey, JSON.stringify({revision, fingerprint:fingerprint(snapshot.data), marks:baseMarks}));
    conflict = null;
  }
  function status(text) {
    message = text;
    if (panel) {
      panel.querySelector('[data-sync-status]').textContent = text;
      panel.querySelector('[data-sync-conflict]').hidden = !conflict;
      panel.querySelector('[data-sync-recovery]').hidden = !localStorage.getItem(recoveryKey);
    }
    if (badge) {
      const label = conflict ? '资料有两个版本，点击核对' : text;
      badge.textContent = label;
      badge.title = label;
      badge.classList.toggle('is-conflict', Boolean(conflict));
      badge.style.color = conflict ? '#9a3412' : '';
    }
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/api/personal-state' + path, {
        method:body === undefined ? 'GET' : 'POST',
        cache:'no-store',
        headers:body === undefined ? {} : {'Content-Type':'application/json'},
        body:body === undefined ? undefined : JSON.stringify(body), signal:controller.signal
      });
      let result;
      try { result = await response.json(); } catch (_) { throw new Error('本机资料接口尚未就绪'); }
      if (!response.ok) {
        const error = new Error(result.error || '本机资料保存失败');
        if (response.status === 409) error.snapshot = result.snapshot;
        throw error;
      }
      return result;
    } finally { clearTimeout(timeout); }
  }
  function replaceLocal(data) {
    const previous = readLocal();
    suppress = true;
    try {
      // Remove first to avoid a temporary doubling of localStorage usage.
      for (const key of keys) nativeRemove.call(localStorage, key);
      for (const [key, value] of Object.entries(data)) {
        if (allowed.has(key) && typeof value === 'string') nativeSet.call(localStorage, key, value);
      }
    } catch (error) {
      for (const key of keys) nativeRemove.call(localStorage, key);
      for (const [key, value] of Object.entries(previous)) nativeSet.call(localStorage, key, value);
      throw error;
    } finally { suppress = false; }
  }
  function hydrate(snapshot, notify = false) {
    if (notify) ensureReloadAllowed();
    replaceLocal(snapshot.data);
    mark(snapshot);
    status('资料已保存到本机服务');
    if (notify) window.dispatchEvent(new Event('personal-state-loaded'));
  }
  function portable(data) {
    return {format:'whq-personal-backup', version:1, created_at:new Date().toISOString(), scope, data};
  }
  function download(data, name) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = name + '-' + new Date().toISOString().slice(0, 10) + '.json';
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function ensureReloadAllowed() {
    if (typeof window.canReloadPersonalState === 'function' && !window.canReloadPersonalState()) {
      throw new Error('AI 正在运行，请结束后再恢复资料');
    }
  }
  const canRefresh = () => typeof window.canRefreshPersonalState !== 'function' || window.canRefreshPersonalState();
  function notifyRefresh() {
    if (renderPending && canRefresh()) {
      renderPending = false;
      window.dispatchEvent(new CustomEvent('personal-state-loaded', {detail:{background:true}}));
    }
  }
  function noteConflict(remote) {
    conflict = remote;
    status('同一项资料有两个版本，请在任务页核对；当前编辑仍保留在浏览器。');
  }
  function archiveLegacy(local) {
    // Complete local recovery copy must succeed before adopting the shared store.
    if (!localStorage.getItem(recoveryKey)) nativeSet.call(localStorage, recoveryKey, JSON.stringify(portable(local)));
    else if (canonical(parse(localStorage.getItem(recoveryKey)).data) !== canonical(local)) {
      throw new Error('旧入口已有待核对的备份，请先导出后核对资料版本');
    }
  }
  async function initialize() {
    try {
      const remote = await request('');
      const local = readLocal();
      let meta = null;
      try { meta = JSON.parse(localStorage.getItem(metaKey)); } catch (_) {}
      if (canonical(local) === canonical(remote.data)) mark(remote);
      else if (remote.revision === 0 && !Object.keys(remote.data).length) {
        mark(await request('/save', {base_revision:0, data:local}));
      } else if (!Object.keys(local).length || (meta && remote.revision >= meta.revision && meta.fingerprint === fingerprint(local))) hydrate(remote);
      else if (meta && meta.marks && remote.revision >= meta.revision) {
        baseMarks = meta.marks;
        let combined;
        try { combined = merge(remote.data, local); }
        catch (_) { noteConflict(remote); return; }
        replaceLocal(combined);
        mark(remote);
        if (canonical(combined) !== baseline) mark(await request('/save', {base_revision:revision, data:combined}));
      } else {
        // Old browsers have no common baseline. Keep their entire copy for
        // recovery, adopt the service version, and import only new calendar IDs.
        try { archiveLegacy(local); }
        catch (error) { noteConflict(remote); status(error.message); return; }
        const combined = {...remote.data};
        const left = indexed(parse(local[logsKey])), right = indexed(parse(remote.data[logsKey] || '[]'));
        if (left && right) combined[logsKey] = JSON.stringify([...Object.values(right), ...Object.values(left).filter(item => !Object.hasOwn(right, item.id))]);
        replaceLocal(combined);
        mark(remote);
        if (canonical(combined) !== baseline) mark(await request('/save', {base_revision:revision, data:combined}));
      }
      status('资料已保存到本机服务');
    } catch (error) {
      if (error.snapshot) noteConflict(error.snapshot);
      if (!conflict) status('仅保存在此浏览器，尚未同步到本机服务');
    } finally { started = true; }
  }
  function reconcile(remote) {
    const local = readLocal();
    let combined;
    try { combined = merge(remote.data, local); }
    catch (error) { noteConflict(remote); throw error; }
    if (canonical(combined) !== canonical(local)) {
      if (!canRefresh()) throw new Error('其他窗口资料已更新，结束当前编辑后自动同步');
      replaceLocal(combined);
      renderPending = true;
    }
    mark(remote);
  }
  function queue() {
    if (suppress) return;
    if (conflict) { status('当前修改保留在浏览器；请先核对资料版本。'); return; }
    status('资料有改动，正在保存…');
    clearTimeout(timer);
    timer = setTimeout(() => flush().catch(() => {}), 700);
  }
  async function flush(attempt = 0) {
    if (attempt >= 12) throw new Error('资料仍在连续编辑，请稍候重试保存');
    await api.ready;
    clearTimeout(timer);
    if (saving) { await saving; return flush(attempt + 1); }
    if (conflict) throw new Error('请先在任务页核对资料版本');
    saving = (async () => {
      if (revision === null) {
        await initialize();
        if (revision === null || conflict) throw new Error('资料尚未同步，请先连接本机服务并核对版本');
      }
      try {
        for (let retry = 0; retry < 5; retry++) {
          const local = readLocal();
          if (canonical(local) === baseline) { notifyRefresh(); return {revision, data:local}; }
          try {
            const saved = await request('/save', {base_revision:revision, data:local});
            mark(saved);
            status('资料已保存到本机服务');
            notifyRefresh();
            return saved;
          } catch (error) {
            if (!error.snapshot) throw error;
            reconcile(error.snapshot);
          }
        }
        throw new Error('其他窗口正在保存，将稍后重试同步');
      } catch (error) {
        if (!conflict) status('保存未成功，修改仍在此浏览器；可点击“重试保存”。');
        throw error;
      }
    })();
    let result;
    try { result = await saving; } finally { saving = null; }
    if (canonical(readLocal()) !== baseline) return flush(attempt + 1);
    return result;
  }
  async function refresh() {
    await api.ready;
    if (saving || conflict || !canRefresh()) return;
    saving = (async () => {
      if (revision === null) {
        await initialize();
        renderPending = true;
      } else {
        const remote = await request('');
        reconcile(remote);
      }
      if (!conflict && revision !== null) status('资料已保存到本机服务');
      notifyRefresh();
    })();
    try { await saving; }
    catch (error) { if (!conflict) status(error.message || '暂未连接本机服务，稍后自动重试'); }
    finally { saving = null; }
    if (!conflict && canonical(readLocal()) !== baseline) await flush().catch(() => {});
  }
  async function reloadFromServer(options = {}) {
    await api.ready;
    ensureReloadAllowed();
    if (saving) await saving;
    const remote = await request('');
    if (canonical(readLocal()) !== baseline && options.discardLocal !== true) {
      conflict = remote;
      status('有未保存的本地修改，请先核对资料版本。');
      throw new Error('本地还有未保存的修改');
    }
    hydrate(remote, true);
    return remote;
  }
  function mount() {
    const target = document.querySelector('#tasks .task-workspace') || document.getElementById('tasks') || document.body;
    panel = document.createElement('section');
    panel.id = 'personal-data-panel'; panel.className = 'task-section';
    panel.innerHTML = '<h3>资料保存与备份</h3><p data-sync-status role="status" aria-live="polite"></p>' +
      '<p class="personal-data-scope"></p>' +
      '<div class="personal-data-actions"><button type="button" class="btn ghost" data-sync-retry>重试保存</button>' +
      '<button type="button" class="btn ghost" data-sync-export>导出资料备份</button>' +
      '<button type="button" class="btn ghost" data-sync-import>恢复资料备份</button>' +
      '<button type="button" class="btn ghost" data-sync-recovery hidden>导出旧入口资料</button>' +
      '<button type="button" class="btn ghost" data-sync-previous>导出恢复前版本</button></div>' +
      '<div data-sync-conflict hidden><p>当前浏览器与本机服务的资料不同。请先导出备份，再选择要继续使用的版本。</p>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn ghost" data-sync-remote-export>导出服务端版本</button>' +
      '<button type="button" class="btn" data-sync-remote>使用本机服务资料</button>' +
      '<button type="button" class="btn ghost" data-sync-local>保存当前浏览器版本</button></div></div>' +
      '<input type="file" accept=".json,application/json" data-sync-file hidden>';
    panel.querySelector('.personal-data-scope').textContent = scope;
    const legacyFile = new URLSearchParams(location.search).get('legacy_file');
    if (legacyFile && /^file:\/\//i.test(legacyFile) && legacyFile.endsWith('?local-backup=1')) {
      nativeSet.call(localStorage, 'whq-personal-legacy-file-v1', legacyFile);
      const url = new URL(location.href); url.searchParams.delete('legacy_file'); history.replaceState(null, '', url);
    }
    const oldFile = localStorage.getItem('whq-personal-legacy-file-v1');
    if (oldFile) {
      const note = document.createElement('p');
      note.textContent = '已统一到本机服务。旧文件入口的资料仍保留在原浏览器；如需导出，在原浏览器地址栏打开下方地址：';
      const address = document.createElement('input'); address.readOnly = true; address.value = oldFile;
      address.setAttribute('aria-label', '旧文件入口备份地址'); address.style.cssText = 'width:100%;min-width:0;box-sizing:border-box';
      panel.append(note, address);
    }
    target.appendChild(panel);
    badge = document.createElement('button'); badge.type = 'button'; badge.id = 'personal-sync-status';
    badge.hidden = true;
    badge.setAttribute('aria-hidden', 'true');
    badge.tabIndex = -1;
    badge.style.display = 'none';
    document.body.appendChild(badge);
    const run = handler => async () => {
      try { await handler(); } catch (error) {
        if (error.snapshot) noteConflict(error.snapshot);
        status(error.message || '操作失败，当前资料未被替换');
      }
    };
    panel.querySelector('[data-sync-retry]').onclick = run(flush);
    panel.querySelector('[data-sync-export]').onclick = () => download(portable(readLocal()), '个人资料');
    const recovery = panel.querySelector('[data-sync-recovery]');
    recovery.hidden = !localStorage.getItem(recoveryKey);
    recovery.onclick = run(async () => download(JSON.parse(localStorage.getItem(recoveryKey)), '旧入口资料'));
    panel.querySelector('[data-sync-remote-export]').onclick = run(async () => download(await request('/backup'), '本机服务资料'));
    panel.querySelector('[data-sync-previous]').onclick = run(async () => download(await request('/previous-backup'), '恢复前资料'));
    panel.querySelector('[data-sync-remote]').onclick = run(async () => {
      ensureReloadAllowed();
      if (!confirm('使用本机服务中的资料？将先下载当前浏览器的资料备份。')) return;
      download(portable(readLocal()), '切换前浏览器资料');
      const remote = await request('');
      hydrate(remote, true);
    });
    panel.querySelector('[data-sync-local]').onclick = run(async () => {
      ensureReloadAllowed();
      if (!conflict || !confirm('用当前浏览器资料替换本机服务版本？服务将自动保留替换前备份。')) return;
      const saved = await request('/restore', {base_revision:conflict.revision, backup:portable(readLocal()), confirm:true});
      mark(saved); status('资料已保存到本机服务');
    });
    const input = panel.querySelector('[data-sync-file]');
    panel.querySelector('[data-sync-import]').onclick = () => input.click();
    input.onchange = run(async () => {
      const file = input.files[0]; input.value = '';
      if (!file) return;
      if (file.size > 20 * 1024 * 1024) throw new Error('备份不能超过 20 MB');
      const backup = JSON.parse(await file.text());
      if (backup.format !== 'whq-personal-backup' || backup.version !== 1 || !backup.data || typeof backup.data !== 'object' || Array.isArray(backup.data)) throw new Error('请选择本平台导出的资料备份');
      if (Object.keys(backup.data).some(key => !allowed.has(key))) throw new Error('备份包含不支持的字段');
      ensureReloadAllowed();
      if (!confirm(`恢复这份备份（${Object.keys(backup.data).length} 类资料）？当前浏览器资料会先下载备份，本机服务也会保留恢复前版本。${scope}`)) return;
      if (saving) await saving;
      const remote = await request('');
      download(portable(readLocal()), '恢复前浏览器资料');
      const restored = await request('/restore', {base_revision:remote.revision, backup, confirm:true});
      hydrate(restored, true);
    });
    status(message);
  }
  Storage.prototype.setItem = function (key, value) {
    const before = this === localStorage && allowed.has(String(key)) ? this.getItem(key) : undefined;
    const result = nativeSet.call(this, key, value);
    if (this === localStorage && allowed.has(String(key)) && before !== String(value)) queue();
    return result;
  };
  Storage.prototype.removeItem = function (key) {
    const changed = this === localStorage && allowed.has(String(key)) && this.getItem(key) !== null;
    const result = nativeRemove.call(this, key);
    if (changed) queue();
    return result;
  };
  window.addEventListener('storage', event => {
    if (event.storageArea === localStorage && (event.key === null || allowed.has(event.key))) {
      renderPending = true;
      clearTimeout(timer);
      timer = setTimeout(() => refresh().catch(() => {}), 150);
    }
  });
  const refreshSoon = () => { if (started) refresh().catch(() => {}); };
  window.addEventListener('online', refreshSoon);
  window.addEventListener('focus', refreshSoon);
  window.addEventListener('pageshow', refreshSoon);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshSoon(); });
  setInterval(() => { if (!document.hidden) refreshSoon(); }, 3000);
  window.addEventListener('beforeunload', event => {
    if (started && canonical(readLocal()) !== baseline) { event.preventDefault(); event.returnValue = ''; }
  });
  const api = {ready:null, flush, refresh, reloadFromServer, keys:keys.slice(),
    get revision() { return revision; }, get hasConflict() { return !!conflict; }};
  window.PersonalSync = api;
  api.ready = initialize();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
