"""一键构建 Windows 发布包

运行: uv run python build_release.py

产出: dist/招聘助手/ 文件夹（可直接压缩为 zip 分发）
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
DIST_DIR = BASE_DIR / "dist"
APP_NAME = "招聘助手"
OUTPUT_DIR = DIST_DIR / APP_NAME

# Playwright 浏览器源路径
PW_BROWSERS_SRC = Path(os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH",
    Path.home() / "AppData" / "Local" / "ms-playwright"
))


def step(msg):
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def clean():
    step("清理旧的构建产物")
    for d in [DIST_DIR / APP_NAME, BASE_DIR / "build"]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            print(f"  已删除 {d}")


def build_frontend():
    step("构建前端")
    frontend_dist = BASE_DIR / "frontend" / "dist"
    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        print("  前端 dist 已存在，跳过构建")
        return
    print("  正在构建前端...")
    subprocess.run(["npm", "run", "build"], cwd=BASE_DIR / "frontend", check=True)


def run_pyinstaller():
    step("PyInstaller 打包")

    # 收集 app 模块下的所有 .py 文件作为 hidden imports
    hidden_imports = []
    app_dir = BASE_DIR / "app"
    for py_file in app_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        module = str(py_file.relative_to(BASE_DIR)).replace(os.sep, ".").replace(".py", "")
        hidden_imports.append(module)

    # 关键第三方包的 hidden imports
    extra_hiddens = [
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "sqlalchemy.dialects.sqlite",
        "pydantic", "pydantic_settings",
        "multipart", "multipart.multipart",
        "bcrypt", "jwt",
        "PIL", "PIL.Image",
        "lark_oapi",
        "PyPDF2",
        "playwright", "playwright.sync_api", "playwright.async_api",
        "httpx", "httpcore", "anyio", "sniffio", "certifi",
        "starlette.responses", "starlette.routing", "starlette.middleware",
        "starlette.middleware.cors",
    ]
    hidden_imports.extend(extra_hiddens)

    hi_args = []
    for h in hidden_imports:
        hi_args.extend(["--hidden-import", h])

    # 数据文件：前端 dist + app 源码（因为 uvicorn 用 import string 加载）
    data_args = [
        "--add-data", f"{BASE_DIR / 'frontend' / 'dist'};frontend/dist",
        "--add-data", f"{BASE_DIR / 'app'};app",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_NAME,
        "--console",  # 保留控制台窗口以显示状态
        "--icon", "NONE",
        *data_args,
        *hi_args,
        str(BASE_DIR / "launcher.py"),
    ]

    print(f"  执行: PyInstaller (hidden imports: {len(hidden_imports)} 个)")
    subprocess.run(cmd, cwd=str(BASE_DIR), check=True)


def copy_extras():
    step("复制附加文件")

    # 1. 预置 .env（带密钥）
    env_src = BASE_DIR / ".env"
    env_dst = OUTPUT_DIR / "default.env"
    if env_src.exists():
        shutil.copy2(env_src, env_dst)
        print(f"  复制 .env -> default.env")

    # 2. Edge 扩展
    ext_src = BASE_DIR / "edge_extension"
    ext_dst = OUTPUT_DIR / "edge_extension"
    if ext_src.exists():
        shutil.copytree(ext_src, ext_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        print(f"  复制 edge_extension/")

    # 3. Playwright 浏览器
    copy_playwright_browsers()

    # 4. 使用说明
    write_readme()


def copy_playwright_browsers():
    step("复制 Playwright Chromium 浏览器")

    dst = OUTPUT_DIR / "playwright-browsers"
    dst.mkdir(exist_ok=True)

    # 只复制 chromium（不需要 firefox/webkit）
    copied = False
    for item in PW_BROWSERS_SRC.iterdir():
        if item.is_dir() and item.name.startswith("chromium-"):
            target = dst / item.name
            print(f"  复制 {item.name}/ (~394MB，请稍候...)")
            shutil.copytree(item, target)
            copied = True

    if not copied:
        print("  [警告] 未找到 Chromium 浏览器！腾讯会议功能将不可用。")
        print(f"  搜索路径: {PW_BROWSERS_SRC}")


def write_readme():
    readme = OUTPUT_DIR / "使用说明.txt"
    readme.write_text(r"""
╔══════════════════════════════════════════════════════════╗
║                  招聘助手 v1.0 使用说明                    ║
╚══════════════════════════════════════════════════════════╝

【快速开始】

  1. 双击 "招聘助手.exe" 启动服务
     → 会自动打开浏览器
     → 首次使用请注册账号

  2. 关闭黑色窗口 = 停止服务


【安装 Edge 扩展（采集Boss直聘简历用）】

  1. 打开 Edge 浏览器（Windows 自带）
  2. 地址栏输入: edge://extensions
  3. 打开左下角 "开发人员模式" 开关
  4. 点击 "加载解压缩的扩展"
  5. 选择本文件夹下的 edge_extension 文件夹
  6. 扩展安装完成，工具栏会出现 "招聘助手" 图标


【使用 Edge 扩展】

  1. 点击扩展图标 → 登录（用网页端注册的账号密码）
  2. 打开 Boss直聘 (zhipin.com) 消息页面
  3. 点击 "自动求简历" — 自动给候选人发消息求简历
  4. 点击 "批量采集简历" — 自动采集已有简历的候选人


【功能说明】

  · 简历管理: 查看、搜索、AI评估所有采集的简历
  · 岗位管理: 创建岗位，设置硬性筛选条件
  · 智能筛选: 按学历、年限、技能自动筛选简历
  · 面试安排: 选候选人+面试官+时间，一键安排
  · 自动通知: 发送飞书消息+创建腾讯会议+飞书日历


【修改配置（高级）】

  如需修改飞书密钥、AI密钥等配置：
  用记事本打开本文件夹下的 .env 文件进行编辑。
  修改后需重启（关闭再打开 招聘助手.exe）。


【常见问题】

  Q: 端口被占用怎么办？
  A: 关闭其他占用 8000 端口的程序，或在 .env 中
     添加一行 APP_PORT=8080 换一个端口。

  Q: 腾讯会议功能怎么用？
  A: 首次使用需要扫码登录腾讯会议账号。
     在面试页面点击"创建会议"会自动打开浏览器让你扫码。
     扫码成功后，后续创建会议都是自动的。

  Q: 数据存在哪里？
  A: 所有数据存储在本文件夹下的 data/ 目录中：
     - data/recruitment.db — 数据库
     - data/resumes/ — 简历PDF文件
     - data/qrcodes/ — 简历二维码
""", encoding="utf-8")
    print(f"  生成使用说明.txt")


def make_zip():
    step("生成 zip 压缩包")
    zip_path = DIST_DIR / f"{APP_NAME}-v1.0-Windows"
    shutil.make_archive(str(zip_path), "zip", str(DIST_DIR), APP_NAME)
    final_zip = f"{zip_path}.zip"
    size_mb = os.path.getsize(final_zip) / (1024 * 1024)
    print(f"  输出: {final_zip}")
    print(f"  大小: {size_mb:.1f} MB")


def main():
    print("招聘助手 Windows 发布包构建工具")
    print(f"Python: {sys.version}")
    print(f"项目目录: {BASE_DIR}")

    clean()
    build_frontend()
    run_pyinstaller()
    copy_extras()
    make_zip()

    step("构建完成！")
    print(f"  发布包位置: {OUTPUT_DIR}")
    print(f"  ZIP 文件: {DIST_DIR / APP_NAME}-v1.0-Windows.zip")
    print(f"\n  可直接将 ZIP 发给 HR 使用。")


if __name__ == "__main__":
    main()
