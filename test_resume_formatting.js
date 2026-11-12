const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

// Test the production formatting functions without a browser or network access.
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const context = vm.createContext({});
vm.runInContext(html.slice(html.indexOf('function escapeHtml('), html.indexOf('function spaceName(')), context);

test('project cards accept date first, title first, and split header rows', () => {
  for (const header of [
    '2026.03 - 2026.05 金融保险 RAG 系统 AI 应用开发',
    '金融保险 RAG 系统｜AI 应用开发\n2026.03 - 2026.05',
    '2026.03 - 2026.05\n金融保险 RAG 系统｜AI 应用开发',
    '金融保险 RAG 系统｜AI 应用开发（2026年3月～2026年5月）',
  ]) {
    const output = context.formatImportedProjects(header + '\n项目介绍：支持混合检索。');
    assert.match(output, /<h3>金融保险 RAG 系统<\/h3>/);
    assert.match(output, /<time>2026/);
    assert.match(output, /resume-imported-project-sub">AI 应用开发/);
    assert.match(output, /支持混合检索。/);
  }
});

test('wrapped PDF bullet text stays in one list item, and section labels remain headings', () => {
  const output = context.formatResumeRichLines([
    '核心设计：',
    ' 守护进程：基于 TCP Socket+',
    'JSON-RPC 2.0 + NDJSON 通信，支持多',
    '客户端订阅。',
    ' 工具管理：记录调用结果。',
    '项目结果：',
    '实现客户端断开重连。',
  ]);
  assert.equal((output.match(/<li>/g) || []).length, 2);
  assert.match(output, /多客户端订阅。<\/li>/);
  assert.match(output, /<h4>项目结果<\/h4>/);
  assert.match(output, /实现客户端断开重连。/);
});

test('explicitly named projects get a heading without inventing dates', () => {
  const output = context.formatImportedProjects('项目名称：库存工具\n完成 CSV 导入。\n项目二：知识库问答\n支持溯源。');
  assert.match(output, /<h3>库存工具<\/h3>/);
  assert.match(output, /<h3>知识库问答<\/h3>/);
  assert.doesNotMatch(output, /<time>/);
});

test('template drafts use their recorded month as project metadata', () => {
  const output = context.formatImportedProjects('项目名称：个人平台\n2026.10\n工作内容：\n- 修复 PDF 容量限制，尚待实际导出核对');
  assert.match(output, /<h3>个人平台<\/h3>/);
  assert.match(output, /<time>2026\.10<\/time>/);
  assert.match(output, /<h4>工作内容<\/h4>/);
  assert.match(output, /尚待实际导出核对/);
  assert.doesNotMatch(output, /至今/);
});

test('skills group by topic and preserve proficiency and mixed English names', () => {
  const skills = '熟悉 Agent 基本原理和核心组件，了\n解规划、执行和结果观察。\n 熟悉 ReAct、MCP，具备 Function\nCalling/MCP 工具编排经验。\n 熟悉 RAG 混合检索。\n 熟练使用 Codex、Claude Code。\n 了解机器学习和 LangChain。\n 了解 MySQL、Redis 数据库。\n 熟悉 Python、FastAPI 后端框架。\n 熟悉使用 Python 完成数据采\n集，熟悉反爬规避。';
  const output = context.formatImportedSkills(skills);
  assert.match(output, /<h3>Agent 与工具<\/h3>/);
  assert.match(output, /了解规划、执行和结果观察。/);
  assert.match(output, /Function Calling\/MCP/);
  assert.match(output, /<h3>RAG 与检索<\/h3>/);
  assert.match(output, /<h3>AI 开发工具<\/h3>/);
  assert.match(output, /<h3>模型与框架<\/h3>/);
  assert.match(output, /了解机器学习和 LangChain。/);
  assert.match(output, /<h3>数据库<\/h3>/);
  assert.match(output, /<h3>后端开发<\/h3>/);
  assert.match(output, /<h3>数据处理<\/h3>/);
  assert.match(output, /数据采集，熟悉反爬规避。/);
  assert.equal((output.match(/<li>/g) || []).length, 8);
});

test('skills and project titles escape imported HTML', () => {
  assert.doesNotMatch(context.formatImportedSkills('- 熟悉 Python <img src=x onerror=alert(1)>'), /<img/);
  assert.doesNotMatch(context.formatImportedProjects('2026.01—2026.03 <script>alert(1)</script>\n项目介绍：测试。'), /<script>/);
});

test('personal headings in skills remain separate display sections', () => {
  const original = { skills:'熟悉 Python。\n荣誉奖项\n数学建模二等奖\n资格证书\n英语四级' };
  const display = context.resumeDisplaySections(original);
  assert.equal(display.skills, '熟悉 Python。');
  assert.equal(display.awards[0], '数学建模二等奖');
  assert.equal(display.qualifications[0], '英语四级');
  assert.equal(original.skills, '熟悉 Python。\n荣誉奖项\n数学建模二等奖\n资格证书\n英语四级');
});

test('technical skills following awards without a heading return to the skills section', () => {
  const source = '技能证书\n能力证书：通过大学英语四级、普通话二级乙等、通过国家计算机三级。\n荣誉奖项\n特等学业奖学金，一等学业奖学金，全国大学生电子商务“创新、创意及创业”挑战赛\n山西省二等奖。\n熟悉 Agent 基本原理和核心组件，了解规划、执行、工具调用、结果观察、继续推理、可观测性的闭环。\n熟悉 ReAct、Reflection、Tool Use、Function Call、MCP、多 Agent 协作等核心机制。\n熟悉 Python 基础与高级特性，熟悉 FastAPI、Flask、Django 后端框架。';
  const display = context.resumeDisplaySections({ skills:source });
  assert.equal(display.qualifications.length, 1);
  assert.equal(display.awards.length, 2);
  assert.match(display.skills, /^熟悉 Agent 基本原理和核心组件/);
  assert.match(display.skills, /熟悉 ReAct、Reflection、Tool Use、Function Call、MCP、多 Agent 协作等核心机制。/);
  assert.doesNotMatch(display.awards.join(''), /Agent|Python/);
  const output = context.formatImportedSkills(display.skills);
  assert.equal((output.match(/<li>/g) || []).length, 3);
  assert.match(output, /熟悉 FastAPI、Flask、Django 后端框架。<\/li>/);
});
