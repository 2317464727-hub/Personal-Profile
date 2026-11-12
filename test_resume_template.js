const assert = require('node:assert/strict');
const test = require('node:test');
const template = require('./resume_template.js');
const row = (type, text) => ({ type, text });

const base = () => ({
  name:'测试用户', role:'AI 应用开发', contacts:['test@example.com'],
  main:[{title:'实习经历', items:[
    row('title', '示例甲有限公司'), row('meta', '2025.12 - 2026.03'), row('bullet', '原有甲公司经历'),
    row('title', '示例乙有限公司'), row('meta', '2026.09 - 至今'), row('bullet', '原有乙公司经历'),
  ]}, {title:'项目经历', items:[row('title', '原有项目'), row('bullet', '项目内容')]}],
  aside:[{title:'教育背景', items:[row('paragraph', '示例大学')]}, {title:'技术与方法', items:[row('label', '数据处理'), row('bullet', 'CSV 字段映射')]}, {title:'荣誉奖项', items:[row('bullet', '数学建模二等奖')]}],
  footer:[{title:'个人优势', items:[row('bullet', '学习主动，注重核对')]}],
});

test('plain resume writing requests and existing update requests open the template', () => {
  for (const text of ['帮我写简历', '给我写一份简历', '你能不能帮我写个简历', '按照现在这个模板生成我的简历', '把这几天做的事写进简历', '更新我的简历', '写简历']) assert.equal(template.isWriteRequest(text), true, text);
  for (const text of ['请总结我的简历内容', '怎么写简历', '不要帮我写简历', '先不整理简历', '帮我写周报', '如何生成简历模板']) assert.equal(template.isWriteRequest(text), false, text);
});

test('resume review requests use the analysis route', () => {
  for (const text of ['根据近 30 天工作优化第一份简历', '帮我看看我的简历哪里不好', '请给我简历改进建议']) assert.equal(template.isImproveRequest(text), true, text);
  for (const text of ['怎么优化简历', '不要帮我优化简历', '帮我看看简历']) assert.equal(template.isImproveRequest(text), false, text);
});

test('new work merges into its original company without touching the next employer', () => {
  const original = base();
  const before = JSON.stringify(original);
  const merged = template.merge(original, [{target:'experience', items:[row('title', '示例甲有限公司'), row('meta', '2026.10'), row('bullet', '新工作，发布仍待测试')]}]);
  const items = merged.main[0].items;
  assert.equal(items.filter((item) => item.type === 'title').length, 2);
  assert.ok(items.findIndex((item) => item.text === '新工作，发布仍待测试') < items.findIndex((item) => item.text === '示例乙有限公司'));
  assert.equal(items[1].text, '2025.12 - 2026.03');
  assert.equal(JSON.stringify(original), before);
});

test('the same company is not repeated when the current draft is reopened', () => {
  const first = {target:'experience', items:[row('title', '示例甲有限公司'), row('meta', '2025.12 - 2026.03'), row('bullet', '新增但尚待测试的工作')]};
  const saved = template.merge(base(), [first]);
  const reopened = template.merge(saved, [first]);
  assert.equal(reopened.main[0].items.filter((item) => item.type === 'title' && item.text === '示例甲有限公司').length, 1);
  assert.equal(reopened.main[0].items.filter((item) => item.text === '新增但尚待测试的工作').length, 1);
});

test('repeated proposals retain one copy and skill groups stay on the right', () => {
  const addition = {target:'skills', items:[row('label', '数据处理'), row('bullet', 'CSV 字段映射'), row('bullet', '规则风险核对')]};
  const result = template.merge(base(), [addition, addition]);
  const items = result.aside.find((section) => section.title === '技术与方法').items;
  assert.equal(items.filter((item) => item.text === '数据处理').length, 1);
  assert.equal(items.filter((item) => item.text === '规则风险核对').length, 1);
  assert.equal(result.main.some((section) => section.title === '技术与方法'), false);
});

test('the full template keeps education and awards beside the body and strengths last', () => {
  const html = template.render(base());
  assert.match(html, /data-template="current-a4-v1"/);
  assert.doesNotMatch(html, /resume-sheet-photo/);
  assert.match(html, /resume-sheet-main">.*实习经历.*项目经历/);
  assert.match(html, /<aside class="resume-sheet-aside">.*教育背景.*技术与方法.*荣誉奖项/);
  assert.match(html, /<footer class="resume-sheet-footer">.*个人优势/);
  assert.ok(html.indexOf('个人优势') > html.indexOf('荣誉奖项'));
  assert.match(html, /原有甲公司经历/);
  assert.match(html, /test@example.com/);
});

test('a saved portrait appears in the preview without exposing markup', () => {
  const payload = base();
  payload.photo = 'data:image/jpeg;base64,abc';
  const html = template.render(payload);
  assert.match(html, /class="resume-sheet-head has-photo"/);
  assert.match(html, /class="resume-sheet-photo" src="data:image\/jpeg;base64,abc"/);
});

test('a preview with no new work still shows the complete saved resume', () => {
  const payload = base();
  assert.deepEqual(template.merge(payload, []), payload);
  assert.match(template.render(template.merge(payload, [])), /示例甲有限公司/);
});

test('untrusted draft text stays escaped and cannot add HTML to the preview', () => {
  const payload = base();
  payload.name = '<img src=x onerror=alert(1)>';
  payload.main[0].items.push(row('bullet', '<script>sample</script>'));
  const html = template.render(payload);
  assert.doesNotMatch(html, /<img|<script/);
  assert.match(html, /&lt;script&gt;sample&lt;\/script&gt;/);
});
