(function (root) {
  'use strict';
  const id = 'current-a4-v1';
  const escape = (text) => String(text == null ? '' : text).replace(/[&<>"']/g, (ch) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
  const key = (text) => String(text || '').replace(/\s+/g, '').toLocaleLowerCase();

  function isWriteRequest(value) {
    const text = String(value || '').trim();
    if (!/简历/.test(text) || /(?:不要|不用|别|暂不|先不|不需要)[^。！？；\n]{0,16}(?:写|生成|整理|修改|更新|补充)/.test(text)) return false;
    if (/(?:怎么|如何|怎样|为什么|是否|是不是|会不会|能不能)[^。！？；\n]*(?:写|生成|整理|修改|更新|补充)/.test(text) && !/(?:帮我|给我|替我|为我)/.test(text)) return false;
    return /(?:写进|写入|写到|写道|写在|放进|放到|放在|加入|添加|补充|更新|修改|整理|整合|生成|完善|改好|填进|填到|同步)/.test(text)
      || /(?:帮我|给我|替我|为我|请)[^。！？；\n]{0,24}写[^。！？；\n]{0,16}简历/.test(text)
      || /(?:^|[，。；\s])写\s*(?:一[份篇版个]|个|份)?\s*(?:我的|个人)?简历/.test(text)
      || /简历[^。！？；\n]{0,12}(?:帮我|给我|替我|为我)[^。！？；\n]{0,8}写/.test(text);
  }

  function isImproveRequest(value) {
    const text = String(value || '').trim();
    return /简历/.test(text)
      && /(?:优化|改进|润色|诊断|不足|问题|建议|打磨|提升|哪里不好|哪里要改|需要改)/.test(text)
      && /(?:帮我|给我|请|根据|结合|我的|这份|第一份|第二份|上传|保存)/.test(text)
      && !/(?:不要|不用|别|暂不|先不|不需要)[^。！？；\n]{0,16}(?:优化|改进|润色|修改)/.test(text);
  }

  function merge(payload, additions) {
    const result = { ...payload };
    for (const column of ['main', 'aside', 'footer']) result[column] = (payload[column] || []).map((section) => ({ ...section, items:section.items.map((item) => ({ ...item })) }));
    for (const addition of additions || []) {
      const config = { experience:['main', '实习经历', 'title'], projects:['main', '项目经历', 'title'], skills:['aside', '技术与方法', 'label'] }[addition.target];
      if (!config || !addition.items?.length) continue;
      const [column, title, heading] = config;
      let section = result[column].find((entry) => entry.title === title);
      if (!section) { section = { title, items:[] }; result[column].push(section); }
      const chunks = [];
      for (const item of addition.items) {
        if (item.type === heading || !chunks.length) chunks.push([]);
        chunks[chunks.length - 1].push({ ...item });
      }
      for (const chunk of chunks) {
        const start = chunk[0].type === heading ? section.items.findIndex((item) => item.type === heading && key(item.text) === key(chunk[0].text)) : -1;
        let incoming = chunk;
        let insert = section.items.length;
        if (start >= 0) {
          insert = start + 1;
          while (insert < section.items.length && section.items[insert].type !== heading) insert++;
          incoming = chunk.slice(1);
          // Existing company roles and project dates remain authoritative.
          if (section.items[start + 1]?.type === 'meta') while (incoming[0]?.type === 'meta') incoming.shift();
        }
        const existing = new Set(section.items.filter((item) => ['paragraph', 'bullet'].includes(item.type)).map((item) => key(item.text)));
        incoming = incoming.filter((item) => {
          if (!['paragraph', 'bullet'].includes(item.type)) return true;
          const signature = key(item.text);
          if (existing.has(signature)) return false;
          existing.add(signature);
          return true;
        });
        section.items.splice(insert, 0, ...incoming);
      }
    }
    result.aside.sort((a, b) => ['教育背景', '技术与方法', '资格证书', '荣誉奖项'].indexOf(a.title) - ['教育背景', '技术与方法', '资格证书', '荣誉奖项'].indexOf(b.title));
    return result;
  }

  function renderItems(items) {
    const html = [];
    let bullets = [];
    const flush = () => { if (bullets.length) html.push('<ul>' + bullets.map((text) => '<li>' + escape(text) + '</li>').join('') + '</ul>'); bullets = []; };
    for (let index = 0; index < items.length; index++) {
      const item = items[index];
      if (item.type === 'bullet') { bullets.push(item.text); continue; }
      flush();
      if (item.type === 'title') {
        const metadata = [];
        while (items[index + 1]?.type === 'meta') metadata.push(items[++index].text);
        html.push('<div class="resume-sheet-entry-head"><h3>' + escape(item.text) + '</h3>' + (metadata.length ? '<span>' + escape(metadata.join(' · ')) + '</span>' : '') + '</div>');
      } else if (item.type === 'label') html.push('<h4>' + escape(item.text) + '</h4>');
      else html.push('<p' + (item.type === 'meta' ? ' class="resume-sheet-meta"' : '') + '>' + escape(item.text) + '</p>');
    }
    flush();
    return html.join('');
  }

  function render(payload) {
    const sections = (items) => (items || []).map((section) => '<section class="resume-sheet-section"><h2>' + escape(section.title) + '</h2>' + renderItems(section.items) + '</section>').join('');
    return '<article class="resume-sheet" aria-label="当前模板简历预览" data-template="' + id + '"><header class="resume-sheet-head' + (payload.photo ? ' has-photo' : '') + '"><div><h1>' + escape(payload.name || '个人简历') + '</h1>' + (payload.role ? '<p>' + escape(payload.role) + '</p>' : '') + '</div>' + (payload.contacts?.length ? '<p class="resume-sheet-contact">' + payload.contacts.map(escape).join(' · ') + '</p>' : '') + (payload.photo ? '<img class="resume-sheet-photo" src="' + escape(payload.photo) + '" alt="简历照片">' : '') + '</header><div class="resume-sheet-columns"><div class="resume-sheet-main">' + sections(payload.main) + '</div>' + (payload.aside?.length ? '<aside class="resume-sheet-aside">' + sections(payload.aside) + '</aside>' : '') + '</div>' + (payload.footer?.length ? '<footer class="resume-sheet-footer">' + sections(payload.footer) + '</footer>' : '') + '</article>';
  }

  const api = { id, isWriteRequest, isImproveRequest, merge, render };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ResumeTemplate = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
