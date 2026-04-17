"""招聘助手启动器

双击运行即可启动后端服务并自动打开浏览器。
适用于 PyInstaller 打包后的独立运行环境。
"""
import os
import sys
import time
import threading
import webbrowser
import socket


def get_base_dir():
    """获取程序所在目录（兼容 PyInstaller 打包和开发模式）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def setup_environment():
    """设置运行环境"""
    base_dir = get_base_dir()
    os.chdir(base_dir)

    # 设置 Playwright 浏览器路径
    browsers_path = os.path.join(base_dir, "playwright-browsers")
    if os.path.isdir(browsers_path):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    # 确保 data 目录存在
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "resumes"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "qrcodes"), exist_ok=True)

    # 首次运行：如果没有 .env，复制默认配置
    env_file = os.path.join(base_dir, ".env")
    env_default = os.path.join(base_dir, "default.env")
    if not os.path.exists(env_file) and os.path.exists(env_default):
        import shutil
        shutil.copy2(env_default, env_file)
        print("[初始化] 已生成默认配置文件 .env")


def is_port_available(port):
    """检查端口是否可用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def open_browser(port):
    """延迟打开浏览器"""
    time.sleep(2.5)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main():
    setup_environment()

    port = int(os.environ.get("APP_PORT", "8000"))

    if not is_port_available(port):
        print(f"\n[错误] 端口 {port} 已被占用！")
        print(f"  可能是招聘助手已经在运行，请检查浏览器访问 http://127.0.0.1:{port}")
        print(f"  或者关闭占用该端口的程序后重试。")
        input("\n按回车键退出...")
        sys.exit(1)

    print("=" * 54)
    print("  招聘助手 v1.0")
    print(f"  访问地址: http://127.0.0.1:{port}")
    print("  ")
    print("  提示: 关闭此窗口将停止服务")
    print("=" * 54)
    print()

    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    except Exception as e:
        print(f"\n[错误] 启动失败: {e}")
        input("\n按回车键退出...")
