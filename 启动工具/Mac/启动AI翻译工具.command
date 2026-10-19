#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$APP_DIR"

APP_NAME="AI 翻译工作台"
SETTINGS_FILE=".translator_settings.json"
MAC_FIRST_RUN_MARKER=".mac_first_run_done"

echo ""
echo "========================================"
echo "  $APP_NAME - Mac 自动启动器"
echo "========================================"
echo ""

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "这个启动器只用于 macOS。"
  echo "Windows 请继续使用 .bat 文件。"
  read -r "?按回车关闭。"
  exit 1
fi

ensure_brew_in_path() {
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

install_homebrew_if_needed() {
  ensure_brew_in_path
  if command -v brew >/dev/null 2>&1; then
    echo "Homebrew 已安装。"
    return 0
  fi

  echo "没有检测到 Homebrew。"
  echo "它用于自动安装 Python、PDF 和 OCR 工具。"
  echo "接下来会调用 Homebrew 官方安装脚本，过程中可能需要输入 Mac 登录密码。"
  echo ""
  read -r "reply?按回车开始安装 Homebrew；输入 n 跳过："
  if [[ "$reply" == "n" || "$reply" == "N" ]]; then
    echo "已跳过 Homebrew 安装，无法继续自动配置。"
    exit 1
  fi

  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ensure_brew_in_path

  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew 安装后仍未进入 PATH。请重新打开此文件再试。"
    read -r "?按回车关闭。"
    exit 1
  fi
}

brew_install_if_needed() {
  local formula="$1"
  if brew list --formula "$formula" >/dev/null 2>&1; then
    echo "$formula 已安装。"
  else
    echo "正在安装 $formula ..."
    brew install "$formula"
  fi
}

install_system_tools() {
  install_homebrew_if_needed
  brew_install_if_needed python
  brew_install_if_needed poppler
  brew_install_if_needed tesseract

  if ! python3 - <<'PY' >/dev/null 2>&1
import tkinter
PY
  then
    echo "当前 Python 缺少 tkinter 文件选择窗口支持，尝试安装 python-tk。"
    if brew info python-tk >/dev/null 2>&1; then
      brew_install_if_needed python-tk
    else
      local py_minor
      py_minor="$(python3 - <<'PY'
import sys
print(f"python-tk@{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
      brew_install_if_needed "$py_minor"
    fi
  fi
}

prepare_python_env() {
  local python_cmd
  python_cmd="$(command -v python3)"
  if [[ -z "$python_cmd" ]]; then
    echo "没有找到 python3。"
    exit 1
  fi

  if [[ ! -d ".venv" ]]; then
    echo "正在创建本地 Python 环境 .venv ..."
    "$python_cmd" -m venv .venv
  fi

  source ".venv/bin/activate"

  echo "正在安装/更新 Python 依赖 ..."
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r "$SCRIPT_DIR/requirements-mac.txt"
}

reset_imported_windows_settings_once() {
  if [[ -f "$MAC_FIRST_RUN_MARKER" ]]; then
    return 0
  fi

  if [[ -f "$SETTINGS_FILE" ]]; then
    echo "检测到已有配置文件。为避免从 U 盘带入旧电脑 API Key，将重置本机配置。"
  fi

  python - <<'PY'
from pathlib import Path
import json
Path(".translator_settings.json").write_text(
    json.dumps(
        {"api_keys": {}, "base_url": "https://example.com/v1", "last_provider": "openai"},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
PY
  touch "$MAC_FIRST_RUN_MARKER"
}

verify_tools() {
  echo "正在检查 PDF/OCR 工具 ..."
  command -v pdftoppm >/dev/null 2>&1 || { echo "未找到 pdftoppm，Poppler 安装可能失败。"; exit 1; }
  command -v tesseract >/dev/null 2>&1 || { echo "未找到 tesseract，Tesseract 安装可能失败。"; exit 1; }

  python - <<'PY'
import pdfplumber
import pypdf
import tkinter
print("Python 依赖检查通过。")
PY
}

install_system_tools
prepare_python_env
reset_imported_windows_settings_once
verify_tools

echo ""
echo "准备完成，正在打开本地网页界面 ..."
echo "API Key 不会从旧电脑带入，请在界面里重新填写并选择是否保存到本机。"
echo ""

python translate_ai_web.py
