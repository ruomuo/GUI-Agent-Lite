"""
GUI Agent Lite - 启动脚本
"""

import os
import sys


def check_dependencies():
    """检查依赖是否已安装"""
    try:
        import pyautogui
        import PIL
        import requests
        import dotenv
        print("✅ 所有依赖已安装")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("\n请运行以下命令安装依赖:")
        print("  pip install -r requirements.txt")
        return False


def main():
    """主函数"""
    print("🤖 GUI Agent Lite (Modern)")
    print("=" * 60)

    if not check_dependencies():
        sys.exit(1)

    if not os.path.exists('.env'):
        print("\n⚠️  未找到 .env 配置文件")
        print("请复制 .env.example 为 .env 并填写配置")

    from gui_agent_modern import MiniGUIAgentApp
    app = MiniGUIAgentApp()
    app.run()


if __name__ == "__main__":
    main()
