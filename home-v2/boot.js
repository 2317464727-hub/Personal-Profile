import { createScene } from "./scene.js?v=20261111-holddrag";

const stage = document.querySelector("#home-stage");
if (!stage) {
  window.syncHomeSceneTheme = () => {};
} else {
  const scene = createScene(stage);
  const reducedQuery = matchMedia("(prefers-reduced-motion: reduce)");
  let reduced = reducedQuery.matches;
  let paused = false;
  let elapsed = 0;
  let previous = performance.now();
  const root = document.documentElement;

  function themeName() {
    return root.getAttribute("data-theme") === "night" ? "dark" : "light";
  }

  function updateZoom(view) {
    const value = document.getElementById("home-zoom-value");
    const inspect = document.getElementById("home-inspect");
    const zoomOut = document.getElementById("home-zoom-out");
    const zoomIn = document.getElementById("home-zoom-in");
    const reset = document.getElementById("home-zoom-reset");
    const hint = document.getElementById("home-zoom-hint");
    if (value) value.textContent = Math.round(view.zoom * 100) + "%";
    if (inspect) inspect.setAttribute("aria-pressed", String(view.inspecting));
    if (zoomOut) zoomOut.disabled = view.zoom <= 1;
    if (zoomIn) zoomIn.disabled = view.zoom >= 4;
    if (reset) reset.disabled = !view.inspecting && view.zoom === 1;
    if (hint) hint.textContent = view.revealed
      ? (view.logCount ? "每个点是一条周历，点圆点或标题打开" : "还没有周历记录")
      : (view.inspecting ? "继续单击或双击放大，按住拖动查看，Esc 复位" : "单击或双击要放大的位置");
  }

  function updateMotion() {
    const stopped = paused || reduced;
    root.toggleAttribute("data-paused", stopped);
    const button = document.getElementById("home-motion");
    const label = document.getElementById("home-motion-label");
    const symbol = document.getElementById("home-motion-symbol");
    if (button) button.setAttribute("aria-pressed", String(stopped));
    if (label) label.textContent = reduced ? "静态模式" : paused ? "继续动效" : "暂停动效";
    if (symbol) symbol.textContent = stopped ? "▷" : "Ⅱ";
  }

  function setMode(mode) {
    document.querySelectorAll("#home [data-home-mode]").forEach((button) => {
      const active = button.dataset.homeMode === mode;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
    scene.setMode(mode);
  }

  stage.addEventListener("sceneviewchange", (event) => updateZoom(event.detail));
  updateZoom(scene.getView());
  scene.setTheme(themeName());
  updateMotion();
  setMode("space");

  document.getElementById("home-inspect")?.addEventListener("click", () => scene.toggleInspection());
  document.getElementById("home-zoom-in")?.addEventListener("click", () => scene.zoomAt(scene.getView().zoom * 1.25));
  document.getElementById("home-zoom-out")?.addEventListener("click", () => scene.zoomAt(scene.getView().zoom / 1.25));
  document.getElementById("home-zoom-reset")?.addEventListener("click", () => scene.resetView());
  document.getElementById("home-motion")?.addEventListener("click", () => {
    if (reduced) return;
    paused = !paused;
    updateMotion();
  });
  document.querySelectorAll("#home [data-home-mode]").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.homeMode));
  });
  reducedQuery.addEventListener("change", (event) => {
    reduced = event.matches;
    updateMotion();
    scene.draw(elapsed, true);
  });

  function syncLogs() {
    if (typeof window.homeSceneLogSource === "function") scene.setLogs(window.homeSceneLogSource());
  }
  window.syncHomeSceneTheme = () => scene.setTheme(themeName());
  window.syncHomeSceneLogs = syncLogs;
  syncLogs();

  function tick(now) {
    const delta = Math.min(0.05, (now - previous) / 1000);
    previous = now;
    const homeOn = document.getElementById("home")?.classList.contains("active");
    if (homeOn && !paused && !reduced) elapsed += delta;
    window.__previewClock = elapsed;
    if (homeOn) scene.draw(elapsed);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  window.addEventListener("pagehide", () => scene.dispose());
}
