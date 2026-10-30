# BNU-ToolBox

BNU-ToolBox 是面向北师大校园学习场景的 Windows 11 桌面工具箱。安装程序已包含 Python
运行时，普通用户无需安装 Python、配置虚拟环境或手工下载 WebDriver。

当前版本只支持：

- Windows 11 x64
- Microsoft Edge

## 功能

插件从在线目录安装，并由各自的 GitHub Release 独立发布和更新。当前目录提供教务抢课、
BNU刷课和校园网认证；也可继续使用 zip 包安装其他插件。

## 安装

从 [GitHub Releases](https://github.com/BNU-ToolBox/BNU-ToolBox/releases/latest)
下载最新版安装包并运行。

安装包尚未配置代码签名证书，Windows 可能显示“未知发布者”。出现此提示时，可选择
“更多信息”后继续安装。

安装程序会请求管理员权限，默认安装到 `C:\Program Files\BNU-ToolBox`，并创建开始菜单
和桌面快捷方式。首次启动后：

1. 在“全局设置”中填写北师大统一身份认证账号。
2. 打开“插件管理”，从在线目录安装所需插件。
3. 在校园网认证插件中填写独立的校园网账号和认证地址。
4. 打开目标插件的“配置”页完成设置，再启动任务。
5. 在“运行”页查看任务流程、总进度、剩余时间和并行进程状态。

系统必须已安装 Microsoft Edge。应用会自动读取 Edge 版本，并从微软官方服务下载匹配
版本的 Edge WebDriver。

## EdgeDriver

全局设置中不提供 WebDriver 路径。驱动由应用自动维护：

- 每次启动 Edge 自动化前检查浏览器版本。
- 缓存位于当前用户数据目录，不写入安装目录。
- 驱动版本不匹配时自动下载对应版本。
- 可在“全局设置”中点击“检测并更新驱动”手动触发。

## 自动更新

主程序启动后会检查 GitHub Release。启用主程序自动更新时，程序会下载最新安装包、
校验 SHA-256，并在 Windows 管理员授权后静默安装和重新启动。

插件更新策略可在“全局设置”中选择：

- 自动更新：启动后安装所有兼容更新。
- 确认后更新：显示可更新插件，由用户确认。
- 从不自动更新：仅保留手动“更新”按钮。

插件版本、主程序最低版本和下载地址来自
[BNUToolboxPlugins](https://github.com/BNU-ToolBox/BNUToolboxPlugins) 索引及其指向的
独立插件仓库。

## 用户数据

程序文件默认安装到 `C:\Program Files\BNU-ToolBox`。可写数据统一保存在：

```text
%LOCALAPPDATA%\BNU-ToolBox
```

该目录包含：

```text
global.json
.credentials.key
logs\
plugins\
installed-plugins\
updates\
runtime\msedgedriver\
```

凭据使用 Fernet 加密，密钥通过 Windows 文件权限限制为当前用户访问。

## 卸载

使用“设置 → 应用 → 已安装的应用”卸载 BNU-ToolBox。默认保留
`%LOCALAPPDATA%\BNU-ToolBox` 中的配置、日志和缓存；如需彻底清除，可在卸载后手动
删除该目录。

## 从源码构建

本节面向参与源码构建的开发者。

开发环境需要：

- Windows 11
- CPython 3.13+ x64
- Inno Setup 6

构建安装包：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

构建脚本会：

1. 创建隔离的 `build/` 目录。
2. 复制 CPython 运行时。
3. 安装锁定依赖到运行时目录。
4. 复制应用、插件 SDK 和静态前端。
5. 调用 Inno Setup 生成安装包。

产物：

```text
dist\installer\BNU-ToolBox-Setup-0.1.0.exe
```

## 项目结构

```text
app/
  core/             配置、路径、EdgeDriver、插件和进程管理
  web/              Vue 3 + Element Plus 静态前端
  api.py            本地 API
  main.py           应用入口
plugins/
  _sdk/             宿主插件 SDK；具体插件从在线目录安装
packaging/           安装包构建脚本和 Inno Setup 配置
```

## 开源协议

本项目采用 MIT License，详见 `LICENSE`。

Python 运行时、Microsoft Edge WebDriver、Python 第三方包和前端组件分别遵循其自身
许可证。安装与再分发说明见 `THIRD_PARTY_NOTICES.md`。

预编译安装包使用 Inno Setup 6.7.3 构建，遵循该版本的非商业使用许可。项目源码采用
MIT License。
