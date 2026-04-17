"""打包脚本 - 将应用打包为 exe"""
import os
import subprocess
import shutil
from pathlib import Path


def build():
    root = Path(__file__).parent
    dist_dir = root / "dist"

    print("=== 招聘助手打包工具 ===\n")

    # 1. 构建前端
    frontend_dir = root / "frontend"
    frontend_dist = frontend_dir / "dist"

    if frontend_dir.exists():
        print("[1/3] 构建前端...")
        subprocess.run(["npm", "run", "build"], cwd=str(frontend_dir), check=True, shell=True)
        print("  前端构建完成\n")
    else:
        print("[1/3] 跳过前端构建（frontend 目录不存在）\n")

    # 2. 复制前端到 app 目录下
    app_frontend = root / "app" / "frontend_dist"
    if frontend_dist.exists():
        if app_frontend.exists():
            shutil.rmtree(app_frontend)
        shutil.copytree(frontend_dist, app_frontend)
        print("  前端文件已复制到 app/frontend_dist\n")

    # 3. 使用 PyInstaller 打包
    print("[2/3] 使用 PyInstaller 打包...")
    cmd = [
        "pyinstaller",
        "--name=招聘助手",
        "--onefile",
        "--add-data", f"app/frontend_dist;frontend_dist",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=app.modules.resume.models",
        "--hidden-import=app.modules.screening.models",
        "--hidden-import=app.modules.scheduling.models",
        "--hidden-import=app.modules.notification.models",
        "--collect-all=app",
        "launcher.py",
    ]

    subprocess.run(cmd, check=True, shell=True)
    print("\n[3/3] 打包完成！")
    print(f"  输出文件: dist/招聘助手.exe")

    # 清理
    if app_frontend.exists():
        shutil.rmtree(app_frontend)


if __name__ == "__main__":
    build()
