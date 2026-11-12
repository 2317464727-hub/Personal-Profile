"use strict";

const readline = require("node:readline");
const path = require("node:path");
const os = require("node:os");

function loadPlaywright() {
  try {
    return require("playwright-core");
  } catch (error) {
    const bundled = path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules", "playwright-core");
    try {
      return require(bundled);
    } catch (missing) {
      throw new Error("缺少 playwright-core。请在 personal 目录运行 npm install。");
    }
  }
}

const { chromium } = loadPlaywright();
const edgePath = process.env.PERSONAL_BROWSER_EXECUTABLE || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const headless = process.env.PERSONAL_BROWSER_HEADLESS !== "0";
let browser = null;
let context = null;
let page = null;

function safeUrl(raw) {
  try {
    const url = new URL(raw);
    for (const key of url.searchParams.keys()) {
      if (/token|secret|password|api.?key|auth|code|session/i.test(key)) url.searchParams.set(key, "***");
    }
    if (/token|secret|password|api.?key|auth|code|session/i.test(url.hash)) url.hash = "#***";
    url.username = "";
    url.password = "";
    return url.toString();
  } catch (error) {
    return "";
  }
}

function checkedUrl(raw) {
  const url = new URL(String(raw || "").trim());
  if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) {
    throw new Error("只支持不带账号密码的 http/https 网址");
  }
  return url.toString();
}

function currentPage() {
  if (!browser || !browser.isConnected() || !context) return null;
  const pages = context.pages().filter((item) => !item.isClosed());
  if (!pages.length) return null;
  if (!page || page.isClosed() || !pages.includes(page)) page = pages[pages.length - 1];
  return page;
}

async function ensureBrowser() {
  if (currentPage()) return page;
  if (browser && browser.isConnected() && context) {
    page = await context.newPage();
    page.setDefaultTimeout(10000);
    return page;
  }
  browser = await chromium.launch({ executablePath:edgePath, headless });
  context = await browser.newContext({ viewport:{ width:1280, height:720 }, acceptDownloads:false });
  context.on("page", (opened) => { page = opened; opened.setDefaultTimeout(10000); });
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  return page;
}

async function status() {
  const active = currentPage();
  if (!active) return { connected:false, title:"", url:"" };
  let title = "";
  try { title = await active.title(); } catch (error) {}
  return { connected:true, title:title.slice(0, 120), url:safeUrl(active.url()) };
}

async function readPage() {
  const active = currentPage();
  if (!active) throw new Error("浏览器尚未打开。先打开一个网址。");
  const content = await active.evaluate(() => {
    document.querySelectorAll("[data-whq-browser-target]").forEach((node) => node.removeAttribute("data-whq-browser-target"));
    const items = [];
    const selector = "a, button, input, textarea, select, [role=button]";
    for (const node of document.querySelectorAll(selector)) {
      if (items.length >= 40) break;
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      if (!rect.width || !rect.height || style.visibility === "hidden" || style.display === "none" || node.disabled) continue;
      const kind = node.tagName.toLowerCase();
      const type = String(node.type || "").toLowerCase();
      if (type === "password" || type === "hidden" || type === "file") continue;
      const label = String(node.getAttribute("aria-label") || node.labels?.[0]?.innerText || node.innerText || node.getAttribute("placeholder") || node.getAttribute("title") || node.getAttribute("name") || "").replace(/\s+/g, " ").trim().slice(0, 90);
      if (!label) continue;
      const id = String(items.length + 1);
      node.setAttribute("data-whq-browser-target", id);
      items.push({ id, kind, label, href:kind === "a" ? node.href || "" : "" });
    }
    return { text:String(document.body?.innerText || "").slice(0, 6500), elements:items };
  });
  content.elements = content.elements.map((item) => ({ ...item, href:safeUrl(item.href) }));
  return { ...await status(), text:content.text, elements:content.elements };
}

function dimension(value, fallback, min, max) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(min, Math.min(max, Math.round(parsed))) : fallback;
}

async function viewPage(args) {
  const active = currentPage();
  if (!active) return { connected:false, title:"", url:"" };
  const width = dimension(args.width, 1280, 320, 1600);
  const height = dimension(args.height, 720, 220, 900);
  const viewport = active.viewportSize();
  if (!viewport || viewport.width !== width || viewport.height !== height) {
    await active.setViewportSize({ width, height });
  }
  const shot = await active.screenshot({ type:"jpeg", quality:72, animations:"disabled", timeout:12000 });
  return { ...await status(), image:shot.toString("base64"), width, height };
}

async function interact(args) {
  const active = currentPage();
  if (!active) throw new Error("浏览器尚未打开");
  const kind = String(args.kind || "");
  if (kind === "click") {
    const viewport = active.viewportSize() || { width:1280, height:720 };
    const x = dimension(args.x, 0, 0, viewport.width - 1);
    const y = dimension(args.y, 0, 0, viewport.height - 1);
    await active.mouse.click(x, y);
  } else if (kind === "scroll") {
    await active.mouse.wheel(
      dimension(args.dx, 0, -1200, 1200),
      dimension(args.dy, 0, -1200, 1200),
    );
  } else if (kind === "type") {
    await active.keyboard.insertText(String(args.text || "").slice(0, 1000));
  } else if (kind === "press") {
    const allowed = new Set(["Enter", "Tab", "Shift+Tab", "Backspace", "Delete", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown", "ControlOrMeta+A"]);
    if (!allowed.has(args.key)) throw new Error("不支持这个按键");
    await active.keyboard.press(args.key);
  } else {
    throw new Error("未知页面操作");
  }
  return status();
}

async function navigate(args) {
  const active = currentPage();
  if (!active) throw new Error("浏览器尚未打开");
  const options = { waitUntil:"domcontentloaded", timeout:15000 };
  if (args.direction === "back") await active.goBack(options);
  else if (args.direction === "forward") await active.goForward(options);
  else if (args.direction === "reload") await active.reload(options);
  else throw new Error("未知导航操作");
  return status();
}

async function run(name, args) {
  if (name === "status") return status();
  if (name === "view") return viewPage(args);
  if (name === "interact") return interact(args);
  if (name === "navigate") return navigate(args);
  if (name === "close") {
    if (browser && browser.isConnected()) await browser.close();
    browser = null; context = null; page = null;
    return { connected:false, title:"", url:"" };
  }
  if (name === "open") {
    const target = checkedUrl(args.url);
    const active = await ensureBrowser();
    await active.goto(target, { waitUntil:"domcontentloaded", timeout:25000 });
    await active.bringToFront();
    return readPage();
  }
  if (name === "read") return readPage();
  if (name === "back") {
    const active = currentPage();
    if (!active) throw new Error("浏览器尚未打开");
    await active.goBack({ waitUntil:"domcontentloaded", timeout:15000 });
    return readPage();
  }
  if (name === "click" || name === "fill") {
    const active = currentPage();
    if (!active) throw new Error("浏览器尚未打开");
    const id = String(args.id || "");
    if (!/^\d{1,2}$/.test(id)) throw new Error("先读取当前页，使用页面元素编号");
    const element = active.locator('[data-whq-browser-target="' + id + '"]');
    if (await element.count() !== 1) throw new Error("页面已变化，请先重新读取当前页");
    if (name === "click") await element.click({ timeout:10000 });
    else {
      const kind = await element.evaluate((node) => node.tagName.toLowerCase());
      const type = await element.evaluate((node) => String(node.type || "").toLowerCase());
      if (!(["input", "textarea"].includes(kind) || await element.getAttribute("contenteditable") === "true") || ["password", "hidden", "file"].includes(type)) {
        throw new Error("只能填写普通文本输入框");
      }
      await element.fill(String(args.text || "").slice(0, 2000));
    }
    await active.waitForLoadState("domcontentloaded", { timeout:5000 }).catch(() => {});
    return readPage();
  }
  throw new Error("未知浏览器命令");
}

const input = readline.createInterface({ input:process.stdin, crlfDelay:Infinity });
let queue = Promise.resolve();
input.on("line", (line) => {
  queue = queue.then(async () => {
    let id = null;
    try {
      const message = JSON.parse(line);
      id = message.id;
      const result = await run(message.name, message.args || {});
      process.stdout.write(JSON.stringify({ id, ok:true, result }) + "\n");
    } catch (error) {
      const detail = String(error.message || error).replace(/(token|secret|password|key|code)=([^\s&]+)/gi, "$1=***");
      process.stdout.write(JSON.stringify({ id, ok:false, error:detail.slice(0, 350) }) + "\n");
    }
  });
});
input.on("close", () => { if (browser && browser.isConnected()) browser.close().catch(() => {}); });
