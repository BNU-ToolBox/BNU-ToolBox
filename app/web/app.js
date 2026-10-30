/* BNU-ToolBox 工具集前端 — Vue 3 + Element Plus (本地 vendor) */
(function () {
  "use strict";

  const { createApp, reactive, ref, computed, watch, nextTick, onMounted } = Vue;
  const El = ElementPlus;
  const Icons = ElementPlusIconsVue;

  // ---------------- API 工具 ----------------

  async function api(path, options) {
    const res = await fetch("/api" + path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const data = await res.json();
        if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      } catch (e) { /* ignore */ }
      throw new Error(detail);
    }
    return res.json();
  }

  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  // ---------------- 状态 ----------------

  const state = reactive({
    page: "dashboard",            // dashboard | plugins | settings | detail
    detailId: null,
    plugins: [],
    catalog: [],
    catalogLoading: false,
    catalogError: "",
    catalogStale: false,
    catalogUpdatedAt: "",
    pluginAction: "",
    promptedPluginUpdates: false,
    globalConfig: null,
    appUpdate: null,
    wsConnected: false,
    themeMode: localStorage.getItem("bnu-toolbox-theme") || "system",
    progress: {},                 // pluginId -> {done,total,workers,...}
    lastStatus: {},               // pluginId -> 最近一次运行状态文本
    stoppingPlugins: {},          // pluginId -> 用户已请求停止
    edgeStatus: null,
    resources: null,
    edgeUpdating: false,
    detailConfig: null,
    detailSchema: [],
    savingConfig: false,
    savingGlobal: false,
    installing: false,
    uiHtml: null,                 // 自定义配置界面 HTML(插件 config_ui 提供)
    detailTab: "run",             // run | config
  });

  // ---------------- WebSocket ----------------

  let ws = null;
  let wsTimer = null;

  function connectWS() {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(proto + location.host + "/api/ws");
    ws.onopen = () => { state.wsConnected = true; };
    ws.onclose = () => {
      state.wsConnected = false;
      clearTimeout(wsTimer);
      wsTimer = setTimeout(connectWS, 2500);
    };
    ws.onerror = () => { try { ws.close(); } catch (e) { /* ignore */ } };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "hello") {
        (msg.history || []).forEach(handleEvent);
      } else {
        handleEvent(msg);
      }
    };
  }

  function handleEvent(msg) {
    const pid = msg.plugin;
    if (!pid) return;
    if (msg.type === "log") {
      // 普通用户只看运行流程；完整日志由主程序写入 logs/plugins/。
      return;
    } else if (msg.type === "progress") {
      if (state.stoppingPlugins[pid]) return;
      const fields = Object.assign({}, msg);
      delete fields.type; delete fields.plugin; delete fields.__event__;
      state.progress[pid] = Object.assign({}, state.progress[pid] || {}, fields);
    } else if (msg.type === "status") {
      if (state.stoppingPlugins[pid]) return;
      state.lastStatus[pid] = msg.text || "";
      const fields = Object.assign({}, msg);
      delete fields.type; delete fields.plugin; delete fields.__event__;
      state.progress[pid] = Object.assign({}, state.progress[pid] || {}, fields);
    } else if (msg.type === "plugin_status") {
      updatePluginStatus(pid, msg.status);
      if (msg.status === "running") {
        delete state.stoppingPlugins[pid];
        delete state.progress[pid];
        state.lastStatus[pid] = "正在启动…";
      } else if (msg.status === "crashed") {
        const info = state.progress[pid];
        if (info && Array.isArray(info.steps)) {
          info.steps = info.steps.map((step) =>
            step.status === "active" ? Object.assign({}, step, { status: "error" }) : step);
        }
        state.lastStatus[pid] = "运行异常退出，请检查配置或网络后重试";
      } else if (msg.status === "stopped") {
        const previous = state.progress[pid] || {};
        state.progress[pid] = {
          stage: "stopped",
          done: 0,
          total: 0,
          overall_percent: 0,
          steps: Array.isArray(previous.steps)
            ? previous.steps.map((step) =>
                Object.assign({}, step, { status: "pending" }))
            : [],
        };
        state.lastStatus[pid] = "已停止";
        delete state.stoppingPlugins[pid];
      }
    } else if (msg.type === "plugin_installed" || msg.type === "plugin_uninstalled") {
      loadPlugins();
      if (state.page === "plugins") loadCatalog(false);
    } else if (msg.type === "plugin_catalog_updated") {
      loadPlugins();
      loadCatalog(true);
      const updated = Array.isArray(msg.updated) ? msg.updated : [];
      if (updated.length) {
        El.ElMessage.success("已自动更新 " + updated.length + " 个插件");
      }
    } else if (msg.type === "app_update") {
      state.appUpdate = Object.assign({}, state.appUpdate || {}, msg);
    } else if (msg.type === "plugin_catalog_error") {
      state.catalogError = msg.message || "插件目录更新失败";
    }
  }

  function updatePluginStatus(pid, status) {
    const p = state.plugins.find((x) => x.id === pid);
    if (p) {
      p.status = status;
      p.running = status === "running" || status === "starting" || status === "stopping";
    }
  }

  // ---------------- 主题 ----------------

  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function applyTheme() {
    const mode = state.themeMode;
    const dark = mode === "dark" || (mode === "system" && media.matches);
    document.documentElement.classList.toggle("dark", dark);
  }

  media.addEventListener("change", () => { if (state.themeMode === "system") applyTheme(); });

  function setThemeMode(mode) {
    state.themeMode = mode;
    localStorage.setItem("bnu-toolbox-theme", mode);
    applyTheme();
  }

  // ---------------- 数据加载 ----------------

  async function loadPlugins() {
    const data = await api("/plugins");
    state.plugins = data.plugins;
    for (const p of state.plugins) {
      if (p.progress && !state.stoppingPlugins[p.id]) {
        state.progress[p.id] = p.progress;
      }
    }
  }

  async function loadCatalog(force) {
    state.catalogLoading = true;
    state.catalogError = "";
    try {
      const data = await api("/plugins/catalog" + (force ? "?refresh=true" : ""));
      state.catalog = data.plugins || [];
      state.catalogStale = data.stale === true;
      state.catalogUpdatedAt = data.updated_at || "";
      if (data.error) state.catalogError = data.error;
      const updates = state.catalog.filter((p) => p.update_available);
      const mode = state.globalConfig
        && state.globalConfig.general
        && state.globalConfig.general.plugin_update_mode;
      if (mode === "confirm" && updates.length && !state.promptedPluginUpdates) {
        state.promptedPluginUpdates = true;
        nextTick(() => promptPluginUpdates(updates));
      }
    } catch (e) {
      state.catalogError = e.message;
    } finally {
      state.catalogLoading = false;
    }
  }

  async function loadAppUpdate(check) {
    try {
      state.appUpdate = check
        ? await api("/system/app-update/check", { method: "POST" })
        : await api("/system/app-update");
    } catch (e) {
      state.appUpdate = {
        status: "error",
        current_version: state.appUpdate ? state.appUpdate.current_version : "",
        message: e.message,
      };
    }
  }

  async function loadGlobal() {
    const data = await api("/global");
    state.globalConfig = data.config;
  }

  let detailRequest = 0;

  async function openDetail(id) {
    const p = state.plugins.find((x) => x.id === id);
    if (!p) return;
    const requestId = ++detailRequest;
    state.detailId = id;
    state.page = "detail";
    state.detailTab = "run";
    state.detailSchema = p.config_schema || [];
    state.detailConfig = null;
    state.uiHtml = null;
    const data = await api("/plugins/" + id + "/config");
    if (requestId !== detailRequest || state.page !== "detail") return;
    if (p.config_ui) {
      // 自定义配置界面插件: 配置对象原样交给界面脚本, 不做编辑模型加工
      state.detailConfig = data.config;
      try {
        const ui = await api("/plugins/" + id + "/ui");
        if (requestId !== detailRequest || state.page !== "detail") return;
        state.uiHtml = ui.html;
      } catch (e) {
        // 界面加载失败时回退到 schema 简易表单, 需要编辑模型
        state.uiHtml = null;
        state.detailConfig = buildEditorModel(state.detailSchema, data.config);
        El.ElMessage.warning("自定义配置界面加载失败, 已回退简易表单: " + e.message);
      }
    } else {
      state.detailConfig = buildEditorModel(state.detailSchema, data.config);
    }
  }

  // ---------------- 配置表单辅助 ----------------

  function coursesToRows(courses) {
    return Object.entries(courses || {}).map(([code, classes]) => ({
      code,
      classes: (classes || []).join(", "),
    }));
  }

  function rowsToCourses(rows) {
    const out = {};
    (rows || []).forEach((r) => {
      const code = (r.code || "").trim();
      if (!code) return;
      const classes = (r.classes || "").split(/[,，\s]+/).filter(Boolean);
      out[code] = classes;
    });
    return out;
  }

  function buildEditorModel(schema, config) {
    // 为 course-table / string-list 生成便于编辑的中间结构
    const model = JSON.parse(JSON.stringify(config || {}));
    schema.forEach((f) => {
      if (f.type === "course-table") {
        model.__rows__ = model.__rows__ || coursesToRows(model[f.key]);
      }
      if (f.type === "string-list") {
        model.__text__ = model.__text__ || {};
        model.__text__[f.key] = (model[f.key] || []).join("\n");
      }
    });
    return model;
  }

  function serializeEditorModel(schema, model) {
    const out = JSON.parse(JSON.stringify(model));
    schema.forEach((f) => {
      if (f.type === "course-table") {
        out[f.key] = rowsToCourses(out.__rows__ || []);
      }
      if (f.type === "string-list") {
        const text = (out.__text__ && out.__text__[f.key]) || "";
        out[f.key] = text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      }
    });
    delete out.__rows__;
    delete out.__text__;
    return out;
  }

  // ---------------- Vue 应用 ----------------

  const app = createApp({
    setup() {
      const detailPlugin = computed(() =>
        state.plugins.find((x) => x.id === state.detailId) || null);

      const runningCount = computed(() => state.plugins.filter((p) => p.running).length);

      const detailModel = computed({
        get: () => state.detailConfig,
        set: (v) => { state.detailConfig = v; },
      });

      onMounted(async () => {
        applyTheme();
        connectWS();
        await loadPlugins();
        await loadGlobal();
        await loadCatalog(false);
        await loadAppUpdate(false);
        await loadEdgeStatus();
        await loadResources();
      });

      const statusText = (p) => ({
        running: "运行中", stopped: "已停止", exited: "已结束",
        crashed: "异常退出", stopping: "停止中…", starting: "启动中…",
      }[p.status] || "已停止");

      const statusTagType = (p) =>
        p.running ? "success" : (p.status === "crashed" ? "danger" : "info");

      const pluginVersionLabel = (p) => {
        if (!p.installed) return "— → v" + (p.latest ? p.latest.version : "?");
        const installed = "v" + (p.installed_version || "?");
        if (!p.latest || !p.update_available) return installed;
        return installed + " → v" + p.latest.version;
      };

      async function refresh() {
        await loadPlugins();
        if (state.page === "plugins") await loadCatalog(false);
      }

      async function loadEdgeStatus() {
        try {
          state.edgeStatus = await api("/system/edge");
        } catch (e) {
          state.edgeStatus = {
            edge_version: "",
            driver_version: "",
            compatible: false,
            edge_path: "",
            driver_path: "",
          };
        }
      }

      async function loadResources() {
        try {
          state.resources = await api("/system/resources");
        } catch (e) {
          state.resources = null;
        }
      }

      async function updateEdgeDriver() {
        state.edgeUpdating = true;
        try {
          const result = await api("/system/edge/driver", {
            method: "POST",
          });
          state.edgeStatus = result.status;
          El.ElMessage.success("Microsoft EdgeDriver 已更新");
        } catch (e) {
          El.ElMessage.error("EdgeDriver 更新失败: " + e.message);
          await loadEdgeStatus();
        } finally {
          state.edgeUpdating = false;
        }
      }

      async function startPlugin(id) {
        try {
          if (id === "campus-network-auth"
              && typeof window.BnuToolBoxCampusSave === "function") {
            const saved = await window.BnuToolBoxCampusSave();
            if (!saved) return;
          }
          if (id === "bdata-autoplay") {
            if (typeof window.BnuToolBoxBnuSave === "function") {
              const saved = await window.BnuToolBoxBnuSave();
              if (!saved) return;
            }
            const data = await api("/plugins/" + id + "/config");
            const cfg = data.config || {};
            const fullAuto = cfg.full_auto === true
              && (cfg.auto_answer === true || cfg.comment_reply === true);
            if (fullAuto) {
              try {
                await El.ElMessageBox.confirm(
                  "当前 BNU刷课已开启全自动模式。模型生成的师道云测验答案、课程评论和回复将不再经过人工核验，确认后可能直接提交。请确认你已检查模型、提示词和操作范围。",
                  "危险：全自动提交",
                  {
                    type: "warning",
                    confirmButtonText: "我已了解，继续启动",
                    cancelButtonText: "取消启动",
                    closeOnClickModal: false,
                    closeOnPressEscape: false,
                  }
                );
              } catch (e) {
                El.ElMessage.info("已取消启动");
                return;
              }
            }
          }
          delete state.progress[id];
          delete state.stoppingPlugins[id];
          state.lastStatus[id] = "正在启动…";
          await post("/plugins/" + id + "/start");
          El.ElMessage.success("已启动");
          await refresh();
        } catch (e) {
          state.lastStatus[id] = "启动失败";
          El.ElMessage.error(e.message);
          await refresh();
        }
      }

      async function stopPlugin(id) {
        state.stoppingPlugins[id] = true;
        updatePluginStatus(id, "stopping");
        resetPluginProgress(id, "正在停止…");
        El.ElMessage.info("停止指令已发送");
        try {
          await post("/plugins/" + id + "/stop");
        } catch (e) {
          delete state.stoppingPlugins[id];
          delete state.progress[id];
          El.ElMessage.error(e.message);
          await refresh();
        }
      }

      async function saveDetailConfig() {
        if (!state.detailConfig) return;
        state.savingConfig = true;
        try {
          const config = serializeEditorModel(state.detailSchema, state.detailConfig);
          await api("/plugins/" + state.detailId + "/config", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config }),
          });
          El.ElMessage.success("配置已保存");
        } catch (e) { El.ElMessage.error(e.message); }
        finally { state.savingConfig = false; }
      }

      async function saveGlobal() {
        state.savingGlobal = true;
        try {
          await api("/global", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config: state.globalConfig }),
          });
          El.ElMessage.success("全局配置已保存");
        } catch (e) { El.ElMessage.error(e.message); }
        finally { state.savingGlobal = false; }
      }

      async function uninstallPlugin(p) {
        try {
          await El.ElMessageBox.confirm(
            "确定删除插件「" + p.name + "」?其配置数据将保留。",
            "删除确认", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
          );
        } catch (e) { return; }
        try {
          await api("/plugins/" + p.id, { method: "DELETE" });
          El.ElMessage.success("已删除");
          await refresh();
        } catch (e) { El.ElMessage.error(e.message); }
      }

      async function installCatalogPlugin(p, update) {
        const verb = update ? "更新" : "安装";
        try {
          await El.ElMessageBox.confirm(
            "确定" + verb + "插件「" + p.name + "」吗？",
            verb + "插件",
            { type: "info", confirmButtonText: verb, cancelButtonText: "取消" }
          );
        } catch (e) { return; }
        state.pluginAction = p.id;
        try {
          const result = await post(
            "/plugins/catalog/" + encodeURIComponent(p.id) + "/install",
            { update: !!update }
          );
          El.ElMessage.success(
            "已" + verb + " " + result.name + " v" + result.version);
          await loadPlugins();
          await loadCatalog(true);
        } catch (e) {
          El.ElMessage.error(e.message);
        } finally {
          state.pluginAction = "";
        }
      }

      async function promptPluginUpdates(updates) {
        try {
          await El.ElMessageBox.confirm(
            "发现 " + updates.length + " 个插件可更新：" +
            updates.map((p) => p.name + " v" + p.latest.version).join("、") +
            "。是否立即安装？",
            "插件更新",
            { type: "info", confirmButtonText: "全部更新", cancelButtonText: "稍后" }
          );
        } catch (e) { return; }
        await updateAllPlugins();
      }

      async function updateAllPlugins() {
        const updates = state.catalog.filter((p) => p.update_available);
        if (!updates.length) return;
        state.pluginAction = "all";
        let failed = 0;
        for (const p of updates) {
          try {
            await post(
              "/plugins/catalog/" + encodeURIComponent(p.id) + "/install",
              { update: true }
            );
          } catch (e) {
            failed += 1;
          }
        }
        state.pluginAction = "";
        await loadPlugins();
        await loadCatalog(true);
        if (failed) El.ElMessage.warning(failed + " 个插件更新失败");
        else El.ElMessage.success("插件已全部更新");
      }

      async function checkAppUpdate() {
        state.pluginAction = "app-update-check";
        await loadAppUpdate(true);
        state.pluginAction = "";
        const info = state.appUpdate || {};
        if (info.status === "error") El.ElMessage.error(info.message);
        else if (info.available) El.ElMessage.warning(info.message);
        else El.ElMessage.success(info.message || "当前已是最新版本");
      }

      async function installAppUpdate() {
        const info = state.appUpdate || {};
        if (!info.available) return;
        try {
          await El.ElMessageBox.confirm(
            "将下载并安装 BNU-ToolBox " + info.latest_version +
            "。安装期间应用会关闭，随后自动重新启动；Windows 可能要求管理员授权。",
            "安装主程序更新",
            { type: "warning", confirmButtonText: "下载并安装", cancelButtonText: "取消" }
          );
        } catch (e) { return; }
        state.pluginAction = "app-update-install";
        try {
          await api("/system/app-update/install", { method: "POST" });
          El.ElMessage.info("安装程序已启动，应用即将重启");
        } catch (e) {
          El.ElMessage.error(e.message);
          state.pluginAction = "";
        }
      }

      function triggerInstall() {
        const input = document.getElementById("zip-input");
        input.value = "";
        input.click();
      }

      async function onZipChosen(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        state.installing = true;
        try {
          const fd = new FormData();
          fd.append("file", file);
          const res = await api("/plugins/install", { method: "POST", body: fd });
          El.ElMessage.success("插件安装成功: " + res.name);
          await refresh();
        } catch (e) { El.ElMessage.error(e.message); }
        finally { state.installing = false; }
      }

      function progressInfo(pid) {
        return state.progress[pid] || null;
      }

      function statusDone(pid) {
        const info = state.progress[pid];
        return !!(info && (info.done === true || info.stage === "finish"));
      }

      function fallbackSteps(pid, stage) {
        if (pid === "bdata-autoplay") {
          return stage === "cache"
            ? [
                { key: "login", label: "登录平台", status: "pending" },
                { key: "course-list", label: "获取课程列表", status: "pending" },
                { key: "details", label: "获取课程详情", status: "pending" },
                { key: "spoc-details", label: "获取 SPOC 课程详情",
                  status: "pending", parent: "details" },
                { key: "bdata-details", label: "获取师道云课程与任务详情",
                  status: "pending", parent: "details" },
              ]
            : [
                { key: "prepare", label: "准备任务", status: "pending" },
                { key: "login", label: "登录平台", status: "pending" },
                { key: "study", label: "视频学习", status: "pending" },
                { key: "qa", label: "答题与互动", status: "pending" },
              ];
        }
        if (pid === "course-grab") {
          return stage === "catalog"
            ? [
                { key: "login", label: "登录教务系统", status: "pending" },
                { key: "catalog", label: "抓取专业目录", status: "pending" },
                { key: "save", label: "保存目录缓存", status: "pending" },
              ]
            : stage === "courses"
              ? [
                  { key: "login", label: "登录教务系统", status: "pending" },
                  { key: "query", label: "查询课程", status: "pending" },
                  { key: "pages", label: "读取课程分页", status: "pending" },
                  { key: "save", label: "保存课程缓存", status: "pending" },
                ]
              : [
                  { key: "config", label: "读取课程配置", status: "pending" },
                  { key: "login", label: "登录教务系统", status: "pending" },
                  { key: "poll", label: "轮询课程余量", status: "pending" },
                  { key: "submit", label: "提交选课", status: "pending" },
                ];
        }
        if (pid === "campus-network-auth") {
          return [
            { key: "network", label: "检测网络", status: "pending" },
            { key: "auth", label: "请求认证", status: "pending" },
            { key: "verify", label: "确认连接", status: "pending" },
          ];
        }
        return [
          { key: "prepare", label: "准备", status: "pending" },
          { key: "run", label: "运行", status: "pending" },
        ];
      }

      function resetPluginProgress(pid, text) {
        const old = state.progress[pid] || {};
        const steps = fallbackSteps(pid, old.stage || "");
        state.progress[pid] = {
          stage: "stopped",
          done: 0,
          total: 0,
          overall_percent: 0,
          steps,
        };
        state.lastStatus[pid] = text;
      }

      function runSteps(pid) {
        const info = state.progress[pid] || {};
        if (Array.isArray(info.steps) && info.steps.length) {
          return info.steps.map((step, index) => ({
            key: String(step.key || index),
            label: step.label || "步骤 " + (index + 1),
            status: ["done", "active", "error"].includes(step.status)
              ? step.status : "pending",
            parent: step.parent ? String(step.parent) : "",
          }));
        }
        const steps = fallbackSteps(pid, info.stage || "");
        if (info.stage === "stopped") {
          return steps.map((step) => ({ ...step, status: "pending" }));
        }
        const done = statusDone(pid);
        const total = Number(info.total) || 0;
        const count = Number(info.done) || 0;
        let activeIndex = 0;
        if (done) activeIndex = steps.length;
        else if (pid === "bdata-autoplay" && info.stage === "cache") {
          activeIndex = total > 0 && count >= total ? 2 : 1;
        } else if (pid === "bdata-autoplay" && info.workers) {
          activeIndex = 2;
        } else if (pid === "course-grab" && info.stage === "catalog") {
          activeIndex = total > 0 && count >= total ? 2 : 1;
        } else if (pid === "course-grab" && info.stage === "courses") {
          activeIndex = total > 0 && count >= total ? 3 : 2;
        } else if (pid === "course-grab" && info.round) {
          activeIndex = 2;
        } else if (pid === "campus-network-auth" && info.total > 0) {
          activeIndex = count >= total ? 3 : 1;
        }
        return steps.map((step, index) => ({
          ...step,
          status: index < activeIndex
            ? "done"
            : index === activeIndex
              ? "active"
              : "pending",
        }));
      }

      function runMainSteps(pid) {
        return runSteps(pid).filter((step) => !step.parent);
      }

      function runChildSteps(pid, parent) {
        return runSteps(pid).filter((step) => step.parent === parent);
      }

      function runMetrics(pid) {
        const info = state.progress[pid] || {};
        let percent = 0;
        if (info.overall_percent !== undefined
            && info.overall_percent !== null
            && Number.isFinite(Number(info.overall_percent))) {
          percent = Number(info.overall_percent);
        } else if (Number(info.total) > 0) {
          percent = Number(info.done || 0) / Number(info.total) * 100;
        } else if (Number(info.qa_total) > 0) {
          percent = Number(info.qa_done || 0) / Number(info.qa_total) * 100;
        } else if (statusDone(pid)) {
          percent = 100;
        }
        const eta = info.eta_s !== undefined && info.eta_s !== null
          ? info.eta_s : info.eta_seconds;
        return {
          percent: Math.max(0, Math.min(100, Number(percent) || 0)),
          etaS: eta !== undefined && eta !== null && isFinite(Number(eta))
            ? Number(eta) : null,
          watchedS: info.watched_seconds !== undefined
            && info.watched_seconds !== null
            && Number.isFinite(Number(info.watched_seconds))
            ? Number(info.watched_seconds) : null,
          totalS: info.total_seconds !== undefined
            && info.total_seconds !== null
            && Number.isFinite(Number(info.total_seconds))
            ? Number(info.total_seconds) : null,
          qaDone: Number(info.qa_done) || 0,
          qaTotal: Number(info.qa_total) || 0,
          qaTitle: info.qa_title || "",
          showEta: info.stage === "study",
        };
      }

      function workerList(pid) {
        const info = state.progress[pid];
        if (!info || !info.workers) return [];
        return Object.entries(info.workers).map(([id, w]) => ({
          id,
          status: w.status || "-",
          course: w.course || "",
          title: w.title || w.url || "",
          percent: typeof w.percent === "number" ? w.percent : null,
          etaS: (w.eta_s === null || w.eta_s === undefined) ? null : w.eta_s,
          totalS: (w.total_s === null || w.total_s === undefined) ? null : w.total_s,
          replays: w.replays || 0,
          watchedS: w.watched_s === undefined ? null : w.watched_s,
        }));
      }

      function workerTagType(s) {
        if (s === "已完成") return "success";
        if (s === "出错" || s === "崩溃") return "danger";
        if (s === "空闲" || s === "已关闭") return "info";
        if (s === "播放中" || s === "重播中") return "";
        return "warning";
      }

      function fmtDur(s) {
        if (s === null || s === undefined || !isFinite(s)) return "-";
        s = Math.max(0, Math.round(s));
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
        return h ? h + ":" + mm + ":" + ss : m + ":" + ss;
      }

      function fmtEta(s) {
        if (s === null || s === undefined || !isFinite(s)) return "-";
        s = Math.round(s);
        if (s < 60) return s + " 秒";
        const m = Math.round(s / 60);
        if (m < 60) return m + " 分";
        return Math.floor(m / 60) + " 时 " + (m % 60) + " 分";
      }

      function fmtEtaClock(s) {
        if (s === null || s === undefined || !isFinite(s)) return "-";
        const d = new Date(Date.now() + s * 1000);
        return String(d.getHours()).padStart(2, "0") + ":" +
               String(d.getMinutes()).padStart(2, "0");
      }

      function addCourseRow() {
        if (!state.detailConfig) return;
        if (!state.detailConfig.__rows__) state.detailConfig.__rows__ = [];
        state.detailConfig.__rows__.push({ code: "", classes: "" });
      }

      function removeCourseRow(idx) {
        if (!state.detailConfig || !state.detailConfig.__rows__) return;
        state.detailConfig.__rows__.splice(idx, 1);
      }

      // ---------------- 自定义配置界面桥(config_ui 插件) ----------------
      // 宿主向界面脚本注入 window.BnuToolBoxConfigUI:
      //   getConfig()  -> Promise<config 对象(密码为 ****** 打码)>
      //   saveConfig(obj) -> Promise 保存(****** 字段由后端保持原值)
      //   api(path, options) -> fetch("/api/"+path) 并按 content-type 解析
      //   post(path, body) -> 便捷 POST JSON
      //   message(type, text) -> 顶部消息(type: success/warning/error/info)
      // 界面 HTML 由 /api/plugins/<id>/ui 下发(已剥离 <style>, 风格用宿主 bnu-* 类)。

      function mountCustomUI(el) {
        if (!el) return;
        const pid = state.detailId || "";
        // 先注入桥再重建脚本节点: 界面脚本执行时 window.BnuToolBoxConfigUI 必须已存在
        window.BnuToolBoxConfigUI = {
          getConfig: async () => {
            const data = await api("/plugins/" + pid + "/config");
            state.detailConfig = data.config;
            return data.config;
          },
          saveConfig: async (cfg) => {
            await api("/plugins/" + pid + "/config", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ config: cfg }),
            });
            state.detailConfig = cfg;
          },
          api: async (path, options) => {
            const res = await fetch("/api/" + String(path).replace(/^\//, ""), options);
            if (!res.ok) {
              let detail = res.statusText;
              try {
                const d = await res.json();
                if (d.detail) detail = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
              } catch (e) { /* ignore */ }
              throw new Error(detail);
            }
            const ct = res.headers.get("content-type") || "";
            return ct.includes("application/json") ? res.json() : res.text();
          },
          post: (path, body) => window.BnuToolBoxConfigUI.api(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: body === undefined ? undefined : JSON.stringify(body),
          }),
          confirm: async (message, title, options) => {
            try {
              await El.ElMessageBox.confirm(message, title || "请确认", {
                type: "warning",
                confirmButtonText: "确认",
                cancelButtonText: "取消",
                ...(options || {}),
              });
              return true;
            } catch (e) {
              return false;
            }
          },
          message: (type, text) => {
            const m = El.ElMessage;
            (m[type] || m.info).call(m, text);
          },
        };
        el.innerHTML = state.uiHtml || "";
        // innerHTML 注入的 <script> 不执行, 需重建节点
        el.querySelectorAll("script").forEach((old) => {
          const s = document.createElement("script");
          s.textContent = old.textContent;
          old.replaceWith(s);
        });
      }

      watch(() => state.uiHtml, () => {
        if (state.page === "detail" && state.detailId) {
          nextTick(() => mountCustomUI(document.getElementById("plugin-ui")));
        }
      });

      watch(() => state.detailId, () => {
        state.uiHtml = null;
      });

      watch(() => state.page, (page) => {
        if (page === "settings") loadEdgeStatus();
        if (page === "plugins") loadCatalog(false);
        if (page === "settings") loadAppUpdate(false);
      });

      return {
        state, detailPlugin, runningCount, detailModel, statusDone,
        statusText, statusTagType, progressInfo, workerList,
        runSteps, runMainSteps, runChildSteps, runMetrics,
        workerTagType, fmtDur, fmtEta, fmtEtaClock,
        startPlugin, stopPlugin, saveDetailConfig, saveGlobal,
        uninstallPlugin, triggerInstall, onZipChosen,
        installCatalogPlugin, updateAllPlugins, checkAppUpdate, installAppUpdate,
        pluginVersionLabel,
        addCourseRow, removeCourseRow, setThemeMode, refresh,
        loadEdgeStatus, updateEdgeDriver, Icons,
      };
    },

    template: `
<div class="layout">
  <input type="file" id="zip-input" accept=".zip" style="display:none" @change="onZipChosen">

  <!-- 侧边栏 -->
  <aside class="sidebar">
    <div class="brand">
      <img class="logo" src="/assets/bnu-toolbox.svg" alt="">
      <div>BNU-ToolBox 工具集<small>大学生活自动化</small></div>
    </div>
    <nav class="nav">
      <div class="nav-item" :class="{active: state.page==='dashboard'}" @click="state.page='dashboard'">
        <el-icon><odometer /></el-icon> 仪表盘
      </div>
      <div class="nav-item" :class="{active: state.page==='plugins'}" @click="state.page='plugins'">
        <el-icon><box /></el-icon> 插件管理
      </div>
      <div class="nav-item" :class="{active: state.page==='settings'}" @click="state.page='settings'">
        <el-icon><setting /></el-icon> 全局设置
      </div>
    </nav>
    <div class="sidebar-foot">
      <span>{{ runningCount }} 个运行中</span>
      <el-radio-group :model-value="state.themeMode" size="small" @update:model-value="setThemeMode">
        <el-radio-button value="light">浅</el-radio-button>
        <el-radio-button value="system">随</el-radio-button>
        <el-radio-button value="dark">深</el-radio-button>
      </el-radio-group>
    </div>
  </aside>

  <!-- 主内容 -->
  <main class="content">

    <!-- 仪表盘 -->
    <template v-if="state.page==='dashboard'">
      <div class="page-header">
        <h1>仪表盘</h1>
        <p>已安装 {{ state.plugins.length }} 个插件</p>
      </div>
      <div class="card-grid">
        <div class="plugin-card" v-for="p in state.plugins" :key="p.id">
          <div class="head">
            <div class="title">
              <div class="icon" style="background:linear-gradient(135deg,var(--bnu-toolbox-accent),var(--bnu-toolbox-accent-2))">
                <el-icon><magic-stick /></el-icon>
              </div>
              <span>{{ p.name }}</span>
            </div>
            <el-tooltip :content="statusText(p)" placement="top">
              <span class="running-dot" v-if="p.running"></span>
              <span class="running-dot" style="background:var(--bnu-toolbox-border);animation:none" v-else></span>
            </el-tooltip>
          </div>
          <div class="desc">{{ p.description }}</div>
          <div class="meta-line">
            <span>v{{ p.version }}</span>
            <span>{{ statusText(p) }}</span>
          </div>
          <div class="actions">
            <el-button v-if="!p.running" type="primary" @click="startPlugin(p.id)">
              <el-icon style="margin-right:4px"><video-play /></el-icon>启动
            </el-button>
            <el-button v-else type="danger" plain @click="stopPlugin(p.id)">
              <el-icon style="margin-right:4px"><video-pause /></el-icon>停止
            </el-button>
            <el-button @click="openDetailById(p.id)">打开</el-button>
          </div>
        </div>
      </div>
    </template>

    <!-- 插件管理 -->
    <template v-if="state.page==='plugins'">
      <div class="page-header">
        <h1>插件管理</h1>
        <p>从在线目录安装插件，或使用 zip 包离线安装</p>
      </div>
      <div class="panel">
        <h2><el-icon><upload /></el-icon> 本地安装</h2>
        <el-button :loading="state.installing" @click="triggerInstall">
          <el-icon style="margin-right:4px"><upload /></el-icon>上传插件 zip 包
        </el-button>
        <span class="form-hint" style="margin-left:12px">
          zip 内需包含 plugin.json 与入口 py 文件(可含一层目录)
        </span>
      </div>
      <div class="panel">
        <div class="catalog-heading">
          <h2><el-icon><box /></el-icon> 插件目录</h2>
          <div class="catalog-actions">
            <span class="form-hint" v-if="state.catalogUpdatedAt">
              更新于 {{ state.catalogUpdatedAt }}
            </span>
            <el-button size="small" :loading="state.catalogLoading" @click="loadCatalog(true)">
              刷新目录
            </el-button>
            <el-button
              v-if="state.catalog.some(p => p.update_available)"
              size="small"
              type="primary"
              :loading="state.pluginAction==='all'"
              @click="updateAllPlugins">
              全部更新
            </el-button>
          </div>
        </div>
        <el-alert
          v-if="state.catalogError"
          :title="state.catalogError"
          :type="state.catalogStale ? 'warning' : 'error'"
          :closable="false"
          show-icon
          style="margin-bottom:12px" />
        <el-table v-loading="state.catalogLoading" :data="state.catalog" style="width:100%">
          <el-table-column label="插件" min-width="230">
            <template #default="scope">
              <div class="catalog-name">
                <strong>{{ scope.row.name }}</strong>
                <el-tag v-if="scope.row.local_only" size="small" type="info" effect="plain">本地</el-tag>
                <el-tag v-if="scope.row.update_available" size="small" type="warning" effect="plain">可更新</el-tag>
              </div>
              <div class="form-hint">{{ scope.row.description }}</div>
            </template>
          </el-table-column>
          <el-table-column label="版本" width="120">
            <template #default="scope">{{ pluginVersionLabel(scope.row) }}</template>
          </el-table-column>
          <el-table-column label="依赖" width="130">
            <template #default="scope">
              <span v-if="scope.row.dependency">宿主 {{ scope.row.dependency }}+</span>
              <span v-else class="form-hint">—</span>
              <el-tag v-if="scope.row.installed && !scope.row.compatible" size="small" type="danger">不兼容</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="安装状态" width="120">
            <template #default="scope">
              <el-tag v-if="!scope.row.installed" size="small" type="info">未安装</el-tag>
              <el-tag v-else :type="statusTagType(scope.row)" size="small">{{ statusText(scope.row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="360">
            <template #default="scope">
              <el-button
                v-if="!scope.row.installed"
                size="small"
                type="primary"
                :disabled="!scope.row.compatible || !scope.row.latest"
                :loading="state.pluginAction===scope.row.id"
                @click="installCatalogPlugin(scope.row, false)">安装</el-button>
              <template v-else>
                <el-button
                  v-if="scope.row.update_available"
                  size="small"
                  type="primary"
                  :loading="state.pluginAction===scope.row.id"
                  @click="installCatalogPlugin(scope.row, true)">更新</el-button>
                <el-button v-if="!scope.row.running" size="small" @click="startPlugin(scope.row.id)">启动</el-button>
                <el-button v-else size="small" type="danger" plain @click="stopPlugin(scope.row.id)">停止</el-button>
                <el-button size="small" @click="openDetailById(scope.row.id)">详情</el-button>
                <el-button size="small" type="danger" plain @click="uninstallPlugin(scope.row)">删除</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <!-- 全局设置 -->
    <template v-if="state.page==='settings' && state.globalConfig">
      <div class="page-header">
        <h1>全局设置</h1>
        <p>北师大统一身份认证账号；BNU刷课固定使用这里的凭据同时登录师道云和 SPOC。凭据使用 Fernet 加密存储。</p>
      </div>
      <div class="panel">
        <h2><el-icon><user /></el-icon> 统一身份认证账号</h2>
        <el-form label-width="90px" style="max-width:560px">
          <el-form-item label="学号">
            <el-input v-model="state.globalConfig.account.username" placeholder="请输入北师大统一身份认证学号" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="state.globalConfig.account.password" type="password" show-password placeholder="已加密存储" />
          </el-form-item>
        </el-form>
      </div>
      <div class="panel">
        <h2><el-icon><tools /></el-icon> 通用参数</h2>
        <el-form label-width="160px" style="max-width:620px">
          <el-form-item label="运行平台">
            <span>Windows 11 · Microsoft Edge</span>
          </el-form-item>
          <el-form-item label="Edge 版本">
            <span v-if="state.edgeStatus && state.edgeStatus.edge_version">
              {{ state.edgeStatus.edge_version }}
            </span>
            <span v-else class="form-hint">未检测到 Microsoft Edge</span>
          </el-form-item>
          <el-form-item label="EdgeDriver">
            <span v-if="state.edgeStatus && state.edgeStatus.driver_version">
              {{ state.edgeStatus.driver_version }}
              <el-tag v-if="state.edgeStatus.compatible" type="success" size="small">兼容</el-tag>
            </span>
            <span v-else class="form-hint">尚未下载</span>
            <el-button
              style="margin-left:12px"
              size="small"
              :loading="state.edgeUpdating"
              @click="updateEdgeDriver">
              检测并更新驱动
            </el-button>
            <div class="form-hint">插件启动时也会自动检测 Edge 版本并下载匹配的 EdgeDriver。</div>
          </el-form-item>
          <el-form-item label="默认无头模式">
            <el-switch v-model="state.globalConfig.general.headless_default" />
          </el-form-item>
          <el-form-item label="系统建议并发">
            <span v-if="state.resources">
              {{ state.resources.recommended_workers }} 个浏览器
              <span class="form-hint">
                （{{ state.resources.physical_cores }} 物理核心 /
                {{ state.resources.total_memory_gb }} GB 内存）
              </span>
            </span>
            <span v-else class="form-hint">正在检测硬件资源</span>
            <div class="form-hint" v-if="state.resources">
              {{ state.resources.formula }}。可在 BNU刷课详情页按需修改。
            </div>
          </el-form-item>
          <el-form-item label="默认播放倍速">
            <el-input-number v-model="state.globalConfig.general.default_speedup" :min="1" :max="16" :step="0.5" />
          </el-form-item>
          <el-form-item label="插件更新策略">
            <el-select v-model="state.globalConfig.general.plugin_update_mode" style="width:280px">
              <el-option value="auto" label="自动更新" />
              <el-option value="confirm" label="确认后更新" />
              <el-option value="never" label="从不自动更新" />
            </el-select>
            <div class="form-hint">
              自动更新会在启动后检查已安装插件；确认后更新会在打开插件管理页时询问。
            </div>
          </el-form-item>
        </el-form>
      </div>
      <div class="panel">
        <h2><el-icon><refresh /></el-icon> 主程序更新</h2>
        <div class="update-summary">
          <div>
            <div class="update-version">
              当前版本 v{{ (state.appUpdate && state.appUpdate.current_version) || "—" }}
            </div>
            <div class="form-hint">
              {{ (state.appUpdate && state.appUpdate.message) || "尚未检查更新" }}
            </div>
          </div>
          <div class="update-actions">
            <el-button
              size="small"
              :loading="state.pluginAction==='app-update-check'"
              @click="checkAppUpdate">检查更新</el-button>
            <el-button
              v-if="state.appUpdate && state.appUpdate.available"
              size="small"
              type="primary"
              :loading="state.pluginAction==='app-update-install'"
              @click="installAppUpdate">下载并安装 v{{ state.appUpdate.latest_version }}</el-button>
          </div>
        </div>
        <el-form label-width="190px" style="max-width:720px;margin-top:14px">
          <el-form-item label="自动安装主程序更新">
            <el-switch v-model="state.globalConfig.general.auto_app_update" />
            <div class="form-hint">
              启动后自动检查、下载并校验 GitHub Release；安装时 Windows 可能显示管理员授权提示。
            </div>
          </el-form-item>
        </el-form>
      </div>
      <el-button type="primary" size="large" :loading="state.savingGlobal" @click="saveGlobal">保存全部设置</el-button>
    </template>

    <!-- 插件详情 -->
    <template v-if="state.page==='detail' && detailPlugin">
      <div class="page-header" style="display:flex;align-items:center;gap:14px">
        <el-button circle aria-label="返回仪表盘" @click="state.page='dashboard'">
          <el-icon><back /></el-icon>
        </el-button>
        <div>
          <h1>{{ detailPlugin.name }} <el-tag size="small" effect="plain">v{{ detailPlugin.version }}</el-tag></h1>
          <p>{{ detailPlugin.description }}</p>
        </div>
        <div style="margin-left:auto;display:flex;gap:8px">
          <el-button v-if="!detailPlugin.running" type="primary" @click="startPlugin(detailPlugin.id)">
            <el-icon style="margin-right:4px"><video-play /></el-icon>启动
          </el-button>
          <el-button v-else type="danger" plain @click="stopPlugin(detailPlugin.id)">
            <el-icon style="margin-right:4px"><video-pause /></el-icon>停止
          </el-button>
        </div>
      </div>

      <div class="detail-tabs" role="tablist" aria-label="插件页面">
        <button
          type="button"
          role="tab"
          :aria-selected="state.detailTab==='run'"
          :class="{active: state.detailTab==='run'}"
          @click="state.detailTab='run'">运行</button>
        <button
          type="button"
          role="tab"
          :aria-selected="state.detailTab==='config'"
          :class="{active: state.detailTab==='config'}"
          @click="state.detailTab='config'">配置</button>
      </div>

      <div v-show="state.detailTab==='run'" role="tabpanel">
        <div
          class="run-overview"
          v-if="progressInfo(detailPlugin.id)">
          <div
            class="sticky-run-summary"
            :class="{'has-eta': runMetrics(detailPlugin.id).showEta}">
            <div class="run-summary-copy">
              <div class="run-summary-label">总进度</div>
              <strong>{{ Math.round(runMetrics(detailPlugin.id).percent) }}%</strong>
              <span class="run-summary-status" aria-live="polite">
                {{ state.lastStatus[detailPlugin.id] || statusText(detailPlugin) }}
              </span>
            </div>
            <div class="run-eta" v-if="runMetrics(detailPlugin.id).showEta">
              <span>剩余时间</span>
              <strong v-if="statusDone(detailPlugin.id)">已完成</strong>
              <strong v-else-if="runMetrics(detailPlugin.id).etaS !== null">
                {{ fmtEta(runMetrics(detailPlugin.id).etaS) }}
              </strong>
              <strong v-else>估算中</strong>
            </div>
            <el-progress
              class="run-total-progress"
              :percentage="runMetrics(detailPlugin.id).percent"
              :stroke-width="12"
              :show-text="false"
              :status="statusDone(detailPlugin.id) ? 'success' : undefined" />
            <div class="run-time-line">
              <span v-if="!statusDone(detailPlugin.id) && runMetrics(detailPlugin.id).watchedS !== null">
                服务器已记录 {{ fmtDur(runMetrics(detailPlugin.id).watchedS) }}
                / {{ fmtDur(runMetrics(detailPlugin.id).totalS) }}
              </span>
              <span v-if="runMetrics(detailPlugin.id).qaTotal">
                答题互动 {{ runMetrics(detailPlugin.id).qaDone }}
                / {{ runMetrics(detailPlugin.id).qaTotal }}
              </span>
            </div>
          </div>

          <div class="run-section-heading">
            <h2>任务流程</h2>
            <span class="form-hint">完成后自动更新</span>
          </div>
          <ol class="run-flow" aria-label="任务步骤">
            <li
              v-for="(step, index) in runMainSteps(detailPlugin.id)"
              :key="step.key"
              class="run-step"
              :class="'is-' + step.status">
              <span class="run-step-marker" aria-hidden="true">
                <el-icon v-if="step.status==='done'"><check /></el-icon>
                <el-icon v-else-if="step.status==='active'" class="is-loading"><loading /></el-icon>
                <el-icon v-else-if="step.status==='error'"><close /></el-icon>
                <span v-else>{{ index + 1 }}</span>
              </span>
              <span class="run-step-copy">
                <strong>{{ step.label }}</strong>
                <small>
                  {{ step.status==='done' ? '已完成'
                    : step.status==='active' ? '进行中'
                    : step.status==='error' ? '异常' : '待完成' }}
                </small>
              </span>
              <ol
                class="run-branches"
                v-if="runChildSteps(detailPlugin.id, step.key).length"
                :aria-label="step.label + '的分支步骤'">
                <li
                  v-for="child in runChildSteps(detailPlugin.id, step.key)"
                  :key="child.key"
                  class="run-branch"
                  :class="'is-' + child.status">
                  <span class="run-branch-marker" aria-hidden="true">
                    <el-icon v-if="child.status==='done'"><check /></el-icon>
                    <el-icon v-else-if="child.status==='active'" class="is-loading"><loading /></el-icon>
                    <el-icon v-else-if="child.status==='error'"><close /></el-icon>
                    <span v-else>·</span>
                  </span>
                  <span>{{ child.label }}</span>
                  <small>
                    {{ child.status==='done' ? '已完成'
                      : child.status==='active' ? '进行中'
                      : child.status==='error' ? '异常' : '待完成' }}
                  </small>
                </li>
              </ol>
            </li>
          </ol>

          <div class="inline-progress-row" v-if="runMetrics(detailPlugin.id).qaTotal">
            <div class="inline-progress-label">
              <strong>答题与互动</strong>
              <span>{{ runMetrics(detailPlugin.id).qaTitle || "处理中" }}</span>
            </div>
            <el-progress
              :percentage="Math.min(100,
                runMetrics(detailPlugin.id).qaDone /
                runMetrics(detailPlugin.id).qaTotal * 100)"
              :stroke-width="9" />
          </div>

          <template v-if="workerList(detailPlugin.id).length">
            <div class="run-section-heading worker-heading">
              <h2>并行进程</h2>
              <span class="form-hint">
                {{ workerList(detailPlugin.id).length }} 个浏览器进程
              </span>
            </div>
            <div class="worker-panels">
              <div class="worker-panel" v-for="w in workerList(detailPlugin.id)" :key="w.id">
                <div class="wp-head">
                  <el-tag size="small" :type="workerTagType(w.status)">进程 #{{ w.id }}</el-tag>
                  <span class="wp-status">{{ w.status }}</span>
                  <span class="wp-title" :title="(w.course ? w.course + ' · ' : '') + w.title">
                    {{ w.course ? w.course + " · " : "" }}{{ w.title || "—" }}
                  </span>
                </div>
                <el-progress
                  v-if="w.percent !== null"
                  :percentage="Math.min(100, Math.round(w.percent * 10) / 10)"
                  :stroke-width="9"
                  :status="w.status === '已完成' ? 'success' : undefined" />
                <div class="wp-meta">
                  <span v-if="w.percent !== null">服务器进度 {{ w.percent }}%</span>
                  <span v-if="w.watchedS !== null">已记录 {{ fmtDur(w.watchedS) }}</span>
                  <span v-if="w.totalS !== null">视频时长 {{ fmtDur(w.totalS) }}</span>
                  <span v-if="w.etaS !== null">剩余 {{ fmtEta(w.etaS) }}</span>
                  <span v-if="w.etaS !== null">预计 {{ fmtEtaClock(w.etaS) }} 完成</span>
                  <span v-if="w.replays">重播 {{ w.replays }} 次</span>
                </div>
              </div>
            </div>
          </template>

          <div
            class="review-link"
            v-if="(state.lastStatus[detailPlugin.id] || '').includes('核验')">
            <span>当前有模型生成内容等待人工核验。</span>
            <el-button type="warning" @click="state.detailTab='config'">前往核验</el-button>
          </div>
        </div>
        <div class="panel empty-state" v-else>
          <p v-if="detailPlugin.running">
            <el-icon class="is-loading"><loading /></el-icon>
            正在初始化任务流程…
          </p>
          <p v-else>暂无运行数据。点击右上角“启动”后，这里会显示流程与实时进度。</p>
        </div>
      </div>

      <div v-show="state.detailTab==='config'" role="tabpanel">
        <div class="panel">
          <h2><el-icon><setting /></el-icon> 插件配置</h2>
          <!-- 自定义配置界面(插件 config_ui 提供; 不含 CSS, 风格由宿主 bnu-* 类统一) -->
          <div v-if="state.uiHtml" id="plugin-ui"></div>
          <template v-else-if="state.detailConfig">
            <el-form label-width="190px" style="max-width:720px">
              <template v-for="f in state.detailSchema" :key="f.key">
                <el-form-item v-if="f.type==='specialty'" :label="f.label">
                  <span class="form-hint">{{ f.hint || "请在插件自定义配置界面中选择" }}</span>
                </el-form-item>
                <el-form-item v-else-if="f.type==='course-table'" :label="f.label">
                  <div style="width:100%">
                    <div class="form-hint" style="margin-bottom:8px" v-if="f.hint">{{ f.hint }}</div>
                    <div class="course-row" v-for="(row, idx) in (state.detailConfig.__rows__ || [])" :key="idx">
                      <el-input class="course-code" v-model="row.code" placeholder="课程代码" />
                      <el-input class="course-classes" v-model="row.classes" placeholder="候选班级号，以逗号分隔（如 09, 10, 11）" />
                      <el-button type="danger" plain circle size="small" aria-label="删除课程" @click="removeCourseRow(idx)">
                        <el-icon><delete /></el-icon>
                      </el-button>
                    </div>
                    <el-button size="small" @click="addCourseRow"><el-icon><plus /></el-icon>添加课程</el-button>
                  </div>
                </el-form-item>
                <el-form-item v-else-if="f.type==='string-list'" :label="f.label">
                  <div style="width:100%">
                    <el-input
                      v-model="state.detailConfig.__text__[f.key]"
                      type="textarea" :rows="8"
                      placeholder="每行填写一个链接…" />
                    <div class="form-hint" style="margin-top:4px" v-if="f.hint">{{ f.hint }}</div>
                  </div>
                </el-form-item>
                <el-form-item v-else-if="f.type==='choice'" :label="f.label">
                  <el-select v-model="state.detailConfig[f.key]" style="width:100%">
                    <el-option
                      v-for="(c, i) in (f.choices || [])" :key="c"
                      :value="c"
                      :label="(f.choice_labels && f.choice_labels[i]) || c" />
                  </el-select>
                </el-form-item>
                <el-form-item v-else-if="f.type==='number'" :label="f.label">
                  <el-input-number
                    v-model="state.detailConfig[f.key]"
                    :min="f.min !== undefined ? f.min : -Infinity"
                    :max="f.max !== undefined ? f.max : Infinity"
                    :step="f.step || 1" />
                </el-form-item>
                <el-form-item v-else-if="f.type==='bool'" :label="f.label">
                  <el-switch v-model="state.detailConfig[f.key]" />
                </el-form-item>
                <el-form-item v-else :label="f.label">
                  <el-input
                    v-model="state.detailConfig[f.key]"
                    :type="f.type==='password' ? 'password' : 'text'"
                    :show-password="f.type==='password'"
                    :placeholder="f.type==='password' ? '已加密存储' : ''" />
                </el-form-item>
              </template>
            </el-form>
            <el-button type="primary" :loading="state.savingConfig" @click="saveDetailConfig">保存配置</el-button>
            <span class="form-hint" style="margin-left:10px">账号留空时使用全局设置；保存后重启插件生效。</span>
          </template>
          <div v-else class="empty-state"><el-icon class="is-loading"><loading /></el-icon> 配置加载中…</div>
        </div>
      </div>
    </template>

  </main>
</div>
`,
    methods: {
      openDetailById(id) { openDetail(id); },
    },
  });

  app.use(El, { locale: ElementPlusLocaleZhCn });
  for (const [name, comp] of Object.entries(Icons)) {
    app.component(name, comp);
  }
  app.mount("#app");
})();
