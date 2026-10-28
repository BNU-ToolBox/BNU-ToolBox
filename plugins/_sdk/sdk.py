"""插件公共 SDK:配置加载、事件上报、Selenium 工具。

插件运行约定:
    python plugin.py --config <runtime_config.json> --datadir <用户数据目录/plugins/<id>>

- 日志直接 print(),由主程序采集并推送前端
- 进度用 ctx.progress() 输出结构化事件,前端渲染进度条
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.edge_driver import ensure_edge_driver  # noqa: E402


# ---------------- 参数与配置 ----------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="运行时配置 JSON 路径")
    parser.add_argument("--datadir", required=True, help="插件数据目录")
    return parser.parse_args(argv)


class PluginContext:
    """每个插件实例持有的上下文:配置、数据目录、事件输出。"""

    def __init__(self, argv: list[str] | None = None):
        args = parse_args(argv)
        self.config_path = Path(args.config)
        self.datadir = Path(args.datadir)
        self.datadir.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config: dict = json.load(f)

    # -- 配置便捷读取 --

    def cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    @property
    def browser(self) -> str:
        return "edge"

    @property
    def username(self) -> str:
        return self.config.get("username", "")

    @property
    def password(self) -> str:
        return self.config.get("password", "")

    # -- 事件输出 --

    def emit(self, event: dict) -> None:
        event["__event__"] = event.get("__event__", "progress")
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def progress(self, **fields: Any) -> None:
        self.emit({"__event__": "progress", **fields})

    def status(self, text: str, **fields: Any) -> None:
        self.emit({"__event__": "status", "text": text, **fields})

    @staticmethod
    def log(msg: str) -> None:
        print(time.strftime("[%H:%M:%S] ") + str(msg), flush=True)


# ---------------- Selenium 工具 ----------------

def _add_chromium_options(opt, headless: bool) -> None:
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--ignore-ssl-errors")
    opt.add_argument("--ignore-certificate-errors")
    opt.add_argument("--autoplay-policy=no-user-gesture-required")
    opt.add_argument("--disable-background-timer-throttling")
    opt.add_argument("--disable-renderer-backgrounding")
    opt.add_argument("--start-maximized")
    if headless:
        opt.add_argument("--headless")
        opt.add_argument("--disable-gpu")
        opt.add_argument("--no-sandbox")
        # 无头下没有真实窗口,必须显式给 16:9 视口,
        # 否则部分站点(SPOC 首页登录按钮等)按视口宽度做响应式隐藏
        opt.add_argument("--window-size=1920,1080")


def make_edge_options(headless: bool = True) -> EdgeOptions:
    opt = EdgeOptions()
    _add_chromium_options(opt, headless)
    return opt


def _configure_window(driver, headless: bool):
    try:
        if headless:
            driver.set_window_size(1920, 1080)
        else:
            driver.maximize_window()
    except WebDriverException:
        pass
    return driver


def make_driver(ctx: PluginContext, headless: bool | None = None):
    if headless is None:
        headless = bool(ctx.cfg("headless", True))
    driver_path = ensure_edge_driver(log=ctx.log)
    service = EdgeService(
        str(driver_path),
        popen_kw={
            "creation_flags": getattr(
                subprocess, "CREATE_NO_WINDOW", 0),
        },
    )
    driver = webdriver.Edge(
        service=service, options=make_edge_options(headless))
    return _configure_window(driver, headless)


def find(driver, element: str, timeout: float = 10, by=By.XPATH):
    """等待元素出现;超时返回 None(dun/main 语义)而非抛异常。"""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, element)))
    except TimeoutException:
        return None


def find_strict(driver, element: str, timeout: float = 10, by=By.XPATH):
    """等待元素出现;超时抛异常(spoc 语义)。"""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, element)))


def sleepran(ti: float) -> None:
    """随机化延迟: 1x ~ 1.5x,模拟人类操作节奏。"""
    time.sleep(ti * (random.random() / 2 + 1))


def speed_hijack_js(speedup: float) -> str:
    return f"""
(function() {{
    if (window.__speedHijacked) return;
    window.__speedHijacked = true;
    const TARGET_SPEED = {speedup};
    const proto = HTMLMediaElement.prototype;
    const originalDesc = Object.getOwnPropertyDescriptor(proto, 'playbackRate');
    if (!originalDesc || !originalDesc.set) return;
    Object.defineProperty(proto, 'playbackRate', {{
        get: function() {{ return originalDesc.get.call(this); }},
        set: function(value) {{ originalDesc.set.call(this, TARGET_SPEED); }},
        configurable: true
    }});
    document.querySelectorAll('video').forEach(v => v.playbackRate = TARGET_SPEED);
}})();
"""


def speed_keeper_js(speedup: float) -> str:
    """周期性把页面所有 video 倍速拉回目标值。

    播放器可能在播放中重建 video 元素或重置倍速,原型劫持不一定覆盖,
    keeper 作为兜底持续生效。与 hijack 同用不冲突。
    """
    return f"""
(function() {{
    window.__bnu-toolboxSpeedTarget = {speedup};
    if (window.__bnu-toolboxSpeedKeeper) return;
    window.__bnu-toolboxSpeedKeeper = true;
    setInterval(function() {{
        const t = window.__bnu-toolboxSpeedTarget || 1;
        document.querySelectorAll('video').forEach(function(v) {{
            try {{
                if (Math.abs(v.playbackRate - t) > 0.01) v.playbackRate = t;
            }} catch (e) {{}}
        }});
    }}, 1500);
}})();
"""


ANTI_PAUSE_JS = """
Object.defineProperty(document, 'visibilityState', {get: () => 'visible'});
Object.defineProperty(document, 'hidden', {get: () => false});
Document.prototype.hasFocus = () => true;
"""
