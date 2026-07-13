#!/usr/bin/env python3
"""Modern local web UI for the AI translation tool."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import socket
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import Tk, filedialog
from urllib.parse import parse_qs, urlparse

import translate_ai


PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
}

SETTINGS_PATH = Path(__file__).resolve().parent / ".translator_settings.json"


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {"api_keys": {}, "base_url": "https://example.com/v1"}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"api_keys": {}, "base_url": "https://example.com/v1"}
        data.setdefault("api_keys", {})
        data.setdefault("base_url", "https://example.com/v1")
        return data
    except Exception:
        return {"api_keys": {}, "base_url": "https://example.com/v1"}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def save_api_key(provider: str, api_key: str, base_url: str = "") -> None:
    settings = load_settings()
    api_keys = settings.setdefault("api_keys", {})
    if api_key:
        api_keys[provider] = api_key
    if base_url:
        settings["base_url"] = base_url
    save_settings(settings)


def clear_api_key(provider: str) -> None:
    settings = load_settings()
    api_keys = settings.setdefault("api_keys", {})
    api_keys.pop(provider, None)
    save_settings(settings)


class QueueWriter:
    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        self.log_queue = log_queue

    def write(self, text: str) -> int:
        if text:
            self.log_queue.put(text)
        return len(text)

    def flush(self) -> None:
        return None


class AppState:
    def __init__(self) -> None:
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.logs: list[str] = []
        self.running = False
        self.done = False
        self.ok = False
        self.output_path = ""
        self.lock = threading.Lock()

    def push(self, text: str) -> None:
        with self.lock:
            self.logs.append(text)


STATE = AppState()


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 翻译工作台</title>
  <style>
    :root {
      --bg: #f6f7f4;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d9e0df;
      --teal: #1f9d8a;
      --teal-dark: #137c70;
      --coral: #e56b5d;
      --blue: #4f7cff;
      --shadow: 0 20px 60px rgba(30, 41, 59, 0.10);
      --radius: 8px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Inter", "Segoe UI", "Microsoft YaHei UI", Arial, sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #fbfbf8 0%, var(--bg) 100%);
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 280px 1fr;
    }
    aside {
      border-right: 1px solid var(--line);
      padding: 28px 22px;
      background: #fbfcfa;
    }
    main { padding: 28px; }
    h1 {
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .sub {
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 14px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 26px;
    }
    .mark {
      width: 34px;
      height: 34px;
      border-radius: 8px;
      background: linear-gradient(135deg, var(--teal), var(--blue));
    }
    .nav-section {
      margin-top: 22px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }
    .nav-title {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 10px;
    }
    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
      margin: 0 0 10px;
    }
    .layout {
      max-width: 1180px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr);
      gap: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .panel-head {
      padding: 18px 18px 0;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .head-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
      min-width: 260px;
    }
    .panel h2 {
      margin: 0;
      font-size: 16px;
      line-height: 1.3;
    }
    .panel-body { padding: 18px; }
    .advanced-details summary {
      list-style: none;
      cursor: pointer;
      padding: 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .advanced-details summary::-webkit-details-marker { display: none; }
    .advanced-details summary::after {
      content: "展开";
      color: var(--teal-dark);
      font-size: 13px;
      font-weight: 750;
    }
    .advanced-details[open] summary::after { content: "收起"; }
    .advanced-details .panel-body {
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .field { grid-column: span 6; }
    .field.full { grid-column: 1 / -1; }
    .field.third { grid-column: span 4; }
    .field.quarter { grid-column: span 3; }
    .field.compact { grid-column: span 4; }
    .simple-hidden { display: none !important; }
    .nav-section { display: none; }
    .layout { max-width: 980px; grid-template-columns: 1fr; }
    aside { padding-top: 32px; }
    .smart-note {
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border: 1px solid #cfe8e2;
      border-radius: 8px;
      background: #f0faf7;
      color: #236b60;
      font-size: 13px;
      line-height: 1.45;
    }
    .smart-note strong {
      display: block;
      color: #155d53;
      font-size: 14px;
      margin-bottom: 2px;
    }
    label {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
      font-weight: 650;
      color: #344054;
    }
    input, select {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 11px;
      font-size: 14px;
      background: #fff;
      color: var(--ink);
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--teal);
      box-shadow: 0 0 0 3px rgba(31, 157, 138, .14);
    }
    .path-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }
    .quick-actions button {
      height: 32px;
      font-size: 12px;
      color: var(--teal-dark);
      background: #eefaf7;
      border-color: #bce6dc;
    }
    button {
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 13px;
      background: #fff;
      color: var(--ink);
      font-weight: 650;
      cursor: pointer;
    }
    button:hover { border-color: #b9c4c2; background: #f8faf9; }
    .primary {
      border-color: var(--teal);
      background: var(--teal);
      color: #fff;
    }
    .primary:hover { background: var(--teal-dark); border-color: var(--teal-dark); }
    .danger {
      border-color: rgba(229, 107, 93, .45);
      color: #a93a30;
      background: #fff7f5;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      height: 26px;
      padding: 0 9px;
      border-radius: 999px;
      background: #eef6f4;
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 700;
    }
    .switch {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      font-size: 14px;
      color: #344054;
    }
    .switch input {
      width: 16px;
      height: 16px;
      box-shadow: none;
    }
    #log {
      height: 310px;
      overflow: auto;
      white-space: pre-wrap;
      background: #111827;
      color: #d8f3ea;
      border-radius: 7px;
      padding: 14px;
      font: 13px/1.5 "Cascadia Mono", Consolas, monospace;
    }
    .status {
      margin-top: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .meter {
      height: 8px;
      border-radius: 999px;
      background: #e6ecea;
      overflow: hidden;
      flex: 1;
    }
    .bar {
      width: 0%;
      height: 100%;
      background: linear-gradient(90deg, var(--teal), var(--blue), var(--coral));
      transition: width .25s ease;
    }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .layout { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      main { padding: 16px; }
      .field, .field.third, .field.quarter { grid-column: 1 / -1; }
      .panel-head { flex-direction: column; }
      .head-actions { width: 100%; justify-content: flex-start; min-width: 0; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <div class="mark"></div>
        <div>
          <h1>AI 翻译工作台</h1>
          <p class="sub">面向论文、PDF 和长文的本地翻译工具。</p>
        </div>
      </div>
      <div class="nav-section">
        <div class="nav-title">Workflow</div>
        <p class="hint">先选 PDF 或 Markdown，再配置模型、目标语言、风格和术语表。</p>
        <p class="hint">长论文会自动分块，并给每块附带文档上下文，减少术语漂移。</p>
      </div>
      <div class="nav-section">
        <div class="nav-title">Glossary</div>
        <p class="hint">支持小型术语表全量注入；大型词典会自动匹配当前分块相关词条。</p>
      </div>
    </aside>
    <main>
      <div class="layout">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>翻译任务</h2>
              <p class="sub">所有文件路径和 API Key 只在本机使用。</p>
            </div>
            <div class="head-actions">
              <span class="pill">Local</span>
              <button class="primary" id="start_btn" onclick="startTask()">开始翻译</button>
              <button onclick="openOutputFolder()">打开输出文件夹</button>
              <button class="danger" onclick="clearLog()">清空日志</button>
            </div>
          </div>
          <div class="panel-body">
            <div class="grid">
              <div class="field full">
                <label>输入文件</label>
                <div class="path-row">
                  <input id="input_path" placeholder="选择 PDF / Markdown / TXT" />
                  <button onclick="choosePath('input')">选择</button>
                </div>
              </div>
              <div class="field full">
                <label>输出文件</label>
                <div class="path-row">
                  <input id="output_path" placeholder="默认保存为 .zh.md" />
                  <button onclick="choosePath('output')">选择</button>
                </div>
              </div>
              <div class="field full">
                <label>术语表 / 词典文件</label>
                <div class="path-row">
                  <input id="glossary_path" placeholder="可选，支持 txt/md/csv/tsv" />
                  <button onclick="choosePath('glossary')">选择</button>
                </div>
                <div class="field full switch" style="margin-top: 8px;">
                  <input id="auto_glossaries" type="checkbox" checked />
                  <span>自动选择内置词典（推荐）</span>
                </div>
                <div class="quick-actions">
                  <button onclick="useBuiltinGlossary('zh_hans')" type="button">手动使用技术词典（简体）</button>
                  <button onclick="clearGlossary()" type="button">不使用词典</button>
                </div>
              </div>
              <div class="field third">
                <label>任务类型</label>
                <select id="workflow_preset" onchange="applyPreset()">
                  <option value="paper_pdf">论文 PDF（推荐）</option>
                  <option value="paper_text">论文文本 / Markdown</option>
                  <option value="quick">快速普通翻译</option>
                  <option value="custom">自定义</option>
                </select>
              </div>
              <div class="field third">
                <label>供应商</label>
                <select id="provider" onchange="providerChanged()">
                  <option>openai</option>
                  <option>anthropic</option>
                  <option>gemini</option>
                  <option>deepseek</option>
                  <option>openai-compatible</option>
                </select>
              </div>
              <div class="field third">
                <label>模型</label>
                <input id="model" />
              </div>
              <div class="field third">
                <label>API Key</label>
                <input id="api_key" type="password" placeholder="粘贴本次使用的 key" />
              </div>
              <div class="field third switch">
                <input id="remember_api_key" type="checkbox" />
                <span>记住 API Key（保存在本机）</span>
              </div>
              <div class="field third">
                <label>已保存 Key</label>
                <button onclick="clearSavedApiKey()" type="button">清除当前供应商 Key</button>
              </div>
              <div class="field full">
                <label>OpenAI-compatible Base URL</label>
                <input id="base_url" value="https://example.com/v1" />
              </div>
              <div class="field quarter">
                <label>源语言</label>
                <input id="source_lang" value="自动识别" />
              </div>
              <div class="field quarter">
                <label>目标语言</label>
                <input id="target_lang" value="简体中文" />
              </div>
              <div class="field quarter">
                <label>翻译风格</label>
                <select id="style">
                  <option value="readable">readable</option>
                  <option value="academic">academic</option>
                  <option value="polished">polished</option>
                  <option value="literal">literal</option>
                </select>
              </div>
              <div class="field quarter">
                <label>翻译水准</label>
                <select id="quality">
                  <option value="standard">standard</option>
                  <option value="high">high</option>
                  <option value="publishable">publishable</option>
                  <option value="fast">fast</option>
                </select>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <details class="advanced-details">
            <summary>
              <div>
                <h2>高级设置</h2>
                <p class="sub">一般不用改。只有扫描 PDF、限流、术语很多时再看这里。</p>
              </div>
            </summary>
            <div class="panel-body">
            <div class="grid">
              <div class="field full">
                <label>PDF 读取方式</label>
                <select id="pdf_engine">
                  <option>auto</option>
                  <option>pdfplumber</option>
                  <option>pypdf</option>
                  <option>pdftotext</option>
                  <option>rapidocr</option>
                  <option>docling</option>
                  <option>marker</option>
                </select>
              </div>
              <div class="field full">
                <label>PDF 文本校验</label>
                <select id="pdf_quality">
                  <option value="balanced">平衡校验（推荐）</option>
                  <option value="strict">严格校验</option>
                  <option value="off">关闭校验</option>
                </select>
              </div>
              <div class="field">
                <label>分块大小</label>
                <input id="max_chars" value="5000" />
              </div>
              <div class="field">
                <label>长文上下文</label>
                <input id="context_chars" value="3000" />
              </div>
              <div class="field">
                <label>每块术语数量</label>
                <input id="glossary_limit" value="80" />
              </div>
              <div class="field">
                <label>请求间隔（秒）</label>
                <input id="sleep" value="1.0" />
              </div>
              <div class="field">
                <label>重试次数</label>
                <input id="retries" value="3" />
              </div>
              <div class="field full switch">
                <input id="keep_page_markers" type="checkbox" />
                <span>保留 PDF 页码，方便回查原文</span>
              </div>
              <div class="field full switch">
                <input id="dry_run" type="checkbox" />
                <span>测试模式，不调用 API</span>
              </div>
              <div class="field full">
                <label>缓存目录</label>
                <div class="path-row">
                  <input id="cache_dir" />
                  <button onclick="choosePath('cache')">选择</button>
                </div>
              </div>
            </div>
            </div>
          </details>
        </section>

        <section class="panel" style="grid-column: 1 / -1;">
          <div class="panel-head">
            <div>
              <h2>运行日志</h2>
              <p class="sub" id="status">等待开始</p>
            </div>
          </div>
          <div class="panel-body">
            <div id="log"></div>
            <div class="status">
              <div class="meter"><div class="bar" id="bar"></div></div>
              <span id="done_text">Idle</span>
            </div>
          </div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const defaults = __DEFAULTS__;
    let logIndex = 0;
    let polling = false;

    document.getElementById("model").value = defaults.models.openai;
    document.getElementById("cache_dir").value = defaults.cache_dir;
    document.getElementById("base_url").value = defaults.saved_base_url || "https://example.com/v1";
    document.getElementById("remember_api_key").checked = true;
    document.getElementById("api_key").value = (defaults.saved_api_keys && defaults.saved_api_keys.openai) || "";

    function providerChanged() {
      const provider = document.getElementById("provider").value;
      document.getElementById("model").value = defaults.models[provider] || "";
      document.getElementById("api_key").value = (defaults.saved_api_keys && defaults.saved_api_keys[provider]) || "";
    }

    function applyPreset() {
      const preset = document.getElementById("workflow_preset").value;
      if (preset === "paper_pdf") {
        document.getElementById("style").value = "academic";
        document.getElementById("quality").value = "high";
        document.getElementById("pdf_engine").value = "auto";
        document.getElementById("pdf_quality").value = "balanced";
        document.getElementById("max_chars").value = "5000";
        document.getElementById("context_chars").value = "3000";
        document.getElementById("glossary_limit").value = "80";
        document.getElementById("keep_page_markers").checked = false;
      } else if (preset === "paper_text") {
        document.getElementById("style").value = "academic";
        document.getElementById("quality").value = "high";
        document.getElementById("max_chars").value = "6000";
        document.getElementById("context_chars").value = "3000";
        document.getElementById("glossary_limit").value = "80";
      } else if (preset === "quick") {
        document.getElementById("style").value = "readable";
        document.getElementById("quality").value = "fast";
        document.getElementById("max_chars").value = "7000";
        document.getElementById("context_chars").value = "1000";
        document.getElementById("glossary_limit").value = "30";
      }
    }

    function useBuiltinGlossary(kind) {
      const path = defaults.builtin_glossaries && defaults.builtin_glossaries[kind];
      if (path) {
        document.getElementById("glossary_path").value = path;
        appendLog("已手动选择技术词典；自动词典模式会在非技术文本中跳过它。\n");
      } else {
        appendLog("未找到内置技术词典，请先导入或手动选择词典文件。\n");
      }
    }

    function clearGlossary() {
      document.getElementById("glossary_path").value = "";
      document.getElementById("auto_glossaries").checked = false;
      appendLog("已关闭词典。\n");
    }

    async function clearSavedApiKey() {
      const provider = document.getElementById("provider").value;
      const res = await fetch("/api/clear-api-key", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({provider})
      });
      const data = await res.json();
      if (data.ok) {
        if (defaults.saved_api_keys) defaults.saved_api_keys[provider] = "";
        document.getElementById("api_key").value = "";
        appendLog("已清除 " + provider + " 的已保存 API Key。\n");
      } else {
        appendLog("清除失败：" + data.error + "\n");
      }
    }

    function formValue(id) { return document.getElementById(id).value.trim(); }
    function formChecked(id) { return document.getElementById(id).checked; }

    async function choosePath(kind) {
      const res = await fetch("/api/choose?kind=" + encodeURIComponent(kind), {method: "POST"});
      const data = await res.json();
      if (!data.path) return;
      const map = {input: "input_path", output: "output_path", glossary: "glossary_path", cache: "cache_dir"};
      document.getElementById(map[kind]).value = data.path;
      if (kind === "input" && !formValue("output_path")) {
        document.getElementById("output_path").value = data.suggested_output || "";
      }
    }

    async function startTask() {
      const body = {
        input_path: formValue("input_path"),
        output_path: formValue("output_path"),
        glossary_path: formValue("glossary_path"),
        auto_glossaries: formChecked("auto_glossaries"),
        provider: formValue("provider"),
        model: formValue("model"),
        api_key: formValue("api_key"),
        remember_api_key: formChecked("remember_api_key"),
        base_url: formValue("base_url"),
        source_lang: formValue("source_lang"),
        target_lang: formValue("target_lang"),
        style: formValue("style"),
        quality: formValue("quality"),
        pdf_engine: formValue("pdf_engine"),
        pdf_quality: formValue("pdf_quality"),
        max_chars: formValue("max_chars"),
        context_chars: formValue("context_chars"),
        glossary_limit: formValue("glossary_limit"),
        sleep: formValue("sleep"),
        retries: formValue("retries"),
        cache_dir: formValue("cache_dir"),
        keep_page_markers: formChecked("keep_page_markers"),
        dry_run: formChecked("dry_run")
      };
      document.getElementById("start_btn").disabled = true;
      document.getElementById("status").textContent = "运行中";
      document.getElementById("done_text").textContent = "Running";
      document.getElementById("bar").style.width = "18%";
      const res = await fetch("/api/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      const data = await res.json();
      if (!data.ok) {
        appendLog("启动失败：" + data.error + "\n");
        document.getElementById("start_btn").disabled = false;
        return;
      }
      if (!polling) pollLogs();
    }

    async function pollLogs() {
      polling = true;
      const res = await fetch("/api/logs?since=" + logIndex);
      const data = await res.json();
      logIndex = data.next;
      for (const line of data.logs) appendLog(line);
      if (data.done) {
        document.getElementById("start_btn").disabled = false;
        document.getElementById("status").textContent = data.ok ? "完成" : "失败";
        document.getElementById("done_text").textContent = data.ok ? "Done" : "Error";
        document.getElementById("bar").style.width = data.ok ? "100%" : "55%";
        polling = false;
        return;
      }
      setTimeout(pollLogs, 800);
    }

    function appendLog(text) {
      const log = document.getElementById("log");
      log.textContent += text;
      log.scrollTop = log.scrollHeight;
    }
    function clearLog() {
      document.getElementById("log").textContent = "";
    }
    async function openOutputFolder() {
      await fetch("/api/open-output-folder", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({path: formValue("output_path")})});
    }
  </script>
</body>
</html>"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 翻译工作台</title>
  <style>
    :root {
      --bg: #f7f8f6;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #6b778c;
      --line: #dce3e1;
      --teal: #1f9d8a;
      --teal-dark: #14796d;
      --blue: #4f7cff;
      --coral: #e56b5d;
      --shadow: 0 20px 50px rgba(23, 32, 51, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Inter", "Segoe UI", "Microsoft YaHei UI", Arial, sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #fbfcfa 0%, var(--bg) 100%);
    }
    .shell {
      min-height: 100vh;
      position: relative;
    }
    aside {
      position: absolute;
      left: 0;
      top: 0;
      width: 240px;
      padding: 36px 26px;
      background: #fbfcfa;
    }
    main {
      padding: 92px clamp(32px, 8vw, 128px) 78px;
    }
    .brand {
      display: flex;
      gap: 14px;
      align-items: center;
    }
    .brand-title {
      display: block;
      white-space: nowrap;
    }
    .mark {
      width: 42px;
      height: 42px;
      flex: 0 0 42px;
      border-radius: 11px;
      background: linear-gradient(135deg, var(--teal), var(--blue));
      box-shadow: 0 10px 20px rgba(47, 129, 247, 0.15);
    }
    h1, h2 {
      margin: 0;
      letter-spacing: 0;
    }
    h1 {
      font-size: 26px;
      line-height: 1.05;
      font-weight: 850;
      white-space: nowrap;
    }
    h2 { font-size: 17px; }
    .sub {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }
    .tagline {
      color: var(--muted);
      display: block;
      margin-top: 5px;
      font-size: 15px;
      line-height: 1.2;
      font-weight: 750;
    }
    .wrap {
      width: min(1120px, 100%);
      margin: 10px auto 0;
      display: grid;
      gap: 16px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .panel-head {
      padding: 18px 20px 0;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
    }
    .panel-body { padding: 20px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .field { grid-column: span 4; }
    .field.full { grid-column: 1 / -1; }
    .field.half { grid-column: span 6; }
    label {
      display: block;
      margin-bottom: 6px;
      color: #344054;
      font-size: 13px;
      font-weight: 700;
    }
    input, select {
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      background: #fff;
      color: var(--ink);
      font-size: 14px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--teal);
      box-shadow: 0 0 0 3px rgba(31, 157, 138, .14);
    }
    .path-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    button {
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 14px;
      background: #fff;
      color: var(--ink);
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    button:hover { background: #f8faf9; border-color: #b8c4c1; }
    button.primary {
      min-width: 120px;
      border-color: var(--teal);
      background: var(--teal);
      color: #fff;
    }
    button.primary:hover { background: var(--teal-dark); border-color: var(--teal-dark); }
    button.danger {
      border-color: rgba(229, 107, 93, .45);
      color: #a93a30;
      background: #fff7f5;
    }
    .actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      background: #eef8f5;
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
    }
    .smart-note {
      grid-column: 1 / -1;
      padding: 12px 14px;
      border: 1px solid #cfe8e2;
      border-radius: 8px;
      background: #f0faf7;
      color: #236b60;
      font-size: 13px;
      line-height: 1.5;
    }
    .smart-note strong {
      display: block;
      color: #155d53;
      font-size: 14px;
      margin-bottom: 2px;
    }
    .switch {
      display: flex;
      align-items: center;
      gap: 9px;
      min-height: 40px;
      color: #344054;
      font-size: 14px;
    }
    .switch input {
      width: 16px;
      height: 16px;
      box-shadow: none;
    }
    details summary {
      list-style: none;
      cursor: pointer;
      padding: 18px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    details summary::-webkit-details-marker { display: none; }
    details summary::after {
      content: "展开";
      color: var(--teal-dark);
      font-size: 13px;
      font-weight: 800;
    }
    details[open] summary::after { content: "收起"; }
    details .panel-body {
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }
    #log {
      height: 240px;
      overflow: auto;
      white-space: pre-wrap;
      border-radius: 8px;
      padding: 14px;
      background: #111827;
      color: #d8f3ea;
      font: 13px/1.5 "Cascadia Mono", Consolas, monospace;
    }
    .status {
      margin-top: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .meter {
      height: 8px;
      border-radius: 999px;
      background: #e6ecea;
      overflow: hidden;
      flex: 1;
    }
    .bar {
      width: 0%;
      height: 100%;
      background: linear-gradient(90deg, var(--teal), var(--blue), var(--coral));
      transition: width .25s ease;
    }
    .hidden { display: none !important; }
    @media (max-width: 900px) {
      .shell { display: block; }
      aside { padding: 24px 22px 8px; border-bottom: 0; }
      aside { position: static; width: auto; }
      main { padding: 18px 16px 44px; }
      h1 { white-space: normal; }
      .brand-title { align-items: flex-start; flex-direction: column; gap: 2px; }
      .field, .field.half { grid-column: 1 / -1; }
      .panel-head { flex-direction: column; }
      .actions { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">
        <div class="mark"></div>
        <div>
          <div class="brand-title">
            <h1>AI 翻译工作台</h1>
            <span class="tagline">选文件，然后开始。</span>
          </div>
        </div>
      </div>
    </aside>
    <main>
      <div class="wrap">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>翻译任务</h2>
            </div>
            <div class="actions">
              <button class="primary" id="start_btn" onclick="startTask()">开始翻译</button>
            </div>
          </div>
          <div class="panel-body">
            <div class="grid">
              <div class="field full">
                <label>输入文件</label>
                <div class="path-row">
                  <input id="input_path" placeholder="选择 PDF / Markdown / TXT" />
                  <button onclick="choosePath('input')">选择</button>
                </div>
              </div>
              <div class="smart-note">
                <strong>智能模式</strong>
                自动选择最可靠的 PDF 读取方式；扫描书会预留 OCR/视觉识别通道；内置词典会按文章内容自动匹配。
              </div>
              <div class="field">
                <label>翻译模式</label>
                <select id="workflow_preset" onchange="applyPreset()">
                  <option value="paper_pdf">论文 PDF（推荐）</option>
                  <option value="paper_text">论文文本 / Markdown</option>
                  <option value="quick">快速普通翻译</option>
                  <option value="custom">自定义</option>
                </select>
              </div>
              <div class="field">
                <label>目标语言</label>
                <input id="target_lang" value="简体中文" />
              </div>
              <div class="field">
                <label>供应商</label>
                <select id="provider" onchange="providerChanged()">
                  <option>openai</option>
                  <option>anthropic</option>
                  <option>gemini</option>
                  <option>deepseek</option>
                  <option>openai-compatible</option>
                </select>
              </div>
              <div class="field half">
                <label>API Key</label>
                <input id="api_key" type="password" placeholder="粘贴 key；可保存到本机" />
              </div>
              <div class="field full switch">
                <input id="remember_api_key" type="checkbox" />
                <span>记住 API Key（只保存在本机）</span>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <details>
            <summary>
              <div>
                <h2>高级设置</h2>
              </div>
            </summary>
            <div class="panel-body">
              <div class="grid">
                <div class="field full">
                  <label>模型</label>
                  <input id="model" />
                </div>
                <div class="field full">
                  <label>输出文件</label>
                  <div class="path-row">
                    <input id="output_path" placeholder="默认保存为 .zh.md" />
                    <button onclick="choosePath('output')">选择</button>
                  </div>
                </div>
                <div class="field full">
                  <label>术语表 / 词典文件</label>
                  <div class="path-row">
                    <input id="glossary_path" placeholder="可选，支持 txt/md/csv/tsv" />
                    <button onclick="choosePath('glossary')">选择</button>
                  </div>
                </div>
                <div class="field full switch">
                  <input id="auto_glossaries" type="checkbox" checked />
                  <span>自动选择内置词典（推荐）</span>
                </div>
                <div class="field half">
                  <button onclick="useBuiltinGlossary('zh_hans')" type="button">手动使用技术词典（简体）</button>
                </div>
                <div class="field half">
                  <button onclick="clearGlossary()" type="button">不使用词典</button>
                </div>
                <div class="field">
                  <label>源语言</label>
                  <input id="source_lang" value="自动识别" />
                </div>
                <div class="field">
                  <label>翻译风格</label>
                  <select id="style">
                    <option value="academic">学术</option>
                    <option value="readable">易读</option>
                    <option value="polished">润色</option>
                    <option value="literal">直译</option>
                  </select>
                </div>
                <div class="field">
                  <label>翻译水准</label>
                  <select id="quality">
                    <option value="high">高质量</option>
                    <option value="standard">标准</option>
                    <option value="publishable">出版级</option>
                    <option value="fast">快速</option>
                  </select>
                </div>
                <div class="field full">
                  <label>OpenAI-compatible Base URL</label>
                  <input id="base_url" value="https://example.com/v1" />
                </div>
                <div class="field">
                  <label>PDF 读取方式</label>
                  <select id="pdf_engine">
                    <option>auto</option>
                    <option>pdftotext-raw</option>
                    <option>pdfplumber</option>
                    <option>pypdf</option>
                    <option>pdftotext</option>
                    <option>tesseract</option>
                    <option>rapidocr</option>
                    <option>docling</option>
                    <option>marker</option>
                  </select>
                </div>
                <div class="field">
                  <label>PDF 文本校验</label>
                  <select id="pdf_quality">
                    <option value="balanced">平衡校验（推荐）</option>
                    <option value="strict">严格校验</option>
                    <option value="off">关闭校验</option>
                  </select>
                </div>
                <div class="field">
                  <label>分块大小</label>
                  <input id="max_chars" value="5000" />
                </div>
                <div class="field">
                  <label>长文上下文</label>
                  <input id="context_chars" value="3000" />
                </div>
                <div class="field">
                  <label>每块术语数量</label>
                  <input id="glossary_limit" value="80" />
                </div>
                <div class="field">
                  <label>请求间隔（秒）</label>
                  <input id="sleep" value="1.0" />
                </div>
                <div class="field">
                  <label>重试次数</label>
                  <input id="retries" value="3" />
                </div>
                <div class="field full switch">
                  <input id="keep_page_markers" type="checkbox" />
                  <span>保留 PDF 页码，方便回查原文</span>
                </div>
                <div class="field full switch">
                  <input id="dry_run" type="checkbox" />
                  <span>测试模式，不调用 API</span>
                </div>
                <div class="field full">
                  <label>缓存目录</label>
                  <div class="path-row">
                    <input id="cache_dir" />
                    <button onclick="choosePath('cache')">选择</button>
                  </div>
                </div>
                <div class="field half">
                  <button onclick="clearSavedApiKey()" type="button">清除当前供应商 Key</button>
                </div>
                <div class="field half">
                  <button class="danger" onclick="clearLog()" type="button">清空日志</button>
                </div>
              </div>
            </div>
          </details>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>运行进度</h2>
              <p class="sub" id="status">等待开始</p>
            </div>
            <span id="done_text">Idle</span>
          </div>
          <div class="panel-body">
            <div class="status" style="margin-top: 0;">
              <div class="meter"><div class="bar" id="bar"></div></div>
            </div>
            <details style="margin-top: 14px;">
              <summary style="padding: 0;">
                <div>
                  <h2 style="font-size: 14px;">详细日志</h2>
                  <p class="sub">展开查看命令输出和错误信息。</p>
                </div>
              </summary>
              <div style="padding-top: 12px;">
              <div id="log"></div>
              </div>
            </details>
          </div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const defaults = __DEFAULTS__;
    let logIndex = 0;
    let polling = false;

    document.getElementById("model").value = defaults.models.openai;
    document.getElementById("cache_dir").value = defaults.cache_dir;
    document.getElementById("base_url").value = defaults.saved_base_url || "https://example.com/v1";
    document.getElementById("remember_api_key").checked = true;
    document.getElementById("api_key").value = (defaults.saved_api_keys && defaults.saved_api_keys.openai) || "";
    applyPreset();

    function providerChanged() {
      const provider = document.getElementById("provider").value;
      document.getElementById("model").value = defaults.models[provider] || "";
      document.getElementById("api_key").value = (defaults.saved_api_keys && defaults.saved_api_keys[provider]) || "";
    }

    function applyPreset() {
      const preset = document.getElementById("workflow_preset").value;
      if (preset === "paper_pdf") {
        document.getElementById("style").value = "academic";
        document.getElementById("quality").value = "high";
        document.getElementById("pdf_engine").value = "auto";
        document.getElementById("pdf_quality").value = "balanced";
        document.getElementById("max_chars").value = "5000";
        document.getElementById("context_chars").value = "3000";
        document.getElementById("glossary_limit").value = "80";
        document.getElementById("keep_page_markers").checked = false;
        document.getElementById("auto_glossaries").checked = true;
      } else if (preset === "paper_text") {
        document.getElementById("style").value = "academic";
        document.getElementById("quality").value = "high";
        document.getElementById("max_chars").value = "6000";
        document.getElementById("context_chars").value = "3000";
        document.getElementById("glossary_limit").value = "80";
        document.getElementById("auto_glossaries").checked = true;
      } else if (preset === "quick") {
        document.getElementById("style").value = "readable";
        document.getElementById("quality").value = "fast";
        document.getElementById("max_chars").value = "7000";
        document.getElementById("context_chars").value = "1000";
        document.getElementById("glossary_limit").value = "30";
        document.getElementById("auto_glossaries").checked = false;
      }
    }

    function useBuiltinGlossary(kind) {
      const path = defaults.builtin_glossaries && defaults.builtin_glossaries[kind];
      if (path) {
        document.getElementById("glossary_path").value = path;
        appendLog("已手动选择技术词典；智能模式会在非技术文本中跳过它。\n");
      } else {
        appendLog("未找到内置技术词典。\n");
      }
    }

    function clearGlossary() {
      document.getElementById("glossary_path").value = "";
      document.getElementById("auto_glossaries").checked = false;
      appendLog("已关闭词典。\n");
    }

    async function clearSavedApiKey() {
      const provider = document.getElementById("provider").value;
      const res = await fetch("/api/clear-api-key", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({provider})
      });
      const data = await res.json();
      if (data.ok) {
        if (defaults.saved_api_keys) defaults.saved_api_keys[provider] = "";
        document.getElementById("api_key").value = "";
        appendLog("已清除 " + provider + " 的已保存 API Key。\n");
      } else {
        appendLog("清除失败：" + data.error + "\n");
      }
    }

    function formValue(id) { return document.getElementById(id).value.trim(); }
    function formChecked(id) { return document.getElementById(id).checked; }

    async function choosePath(kind) {
      const res = await fetch("/api/choose?kind=" + encodeURIComponent(kind), {method: "POST"});
      const data = await res.json();
      if (!data.path) return;
      const map = {input: "input_path", output: "output_path", glossary: "glossary_path", cache: "cache_dir"};
      document.getElementById(map[kind]).value = data.path;
      if (kind === "input") {
        document.getElementById("output_path").value = data.suggested_output || "";
      }
    }

    async function startTask() {
      const body = {
        input_path: formValue("input_path"),
        output_path: formValue("output_path"),
        glossary_path: formValue("glossary_path"),
        auto_glossaries: formChecked("auto_glossaries"),
        provider: formValue("provider"),
        model: formValue("model"),
        api_key: formValue("api_key"),
        remember_api_key: formChecked("remember_api_key"),
        base_url: formValue("base_url"),
        source_lang: formValue("source_lang"),
        target_lang: formValue("target_lang"),
        style: formValue("style"),
        quality: formValue("quality"),
        pdf_engine: formValue("pdf_engine"),
        pdf_quality: formValue("pdf_quality"),
        max_chars: formValue("max_chars"),
        context_chars: formValue("context_chars"),
        glossary_limit: formValue("glossary_limit"),
        sleep: formValue("sleep"),
        retries: formValue("retries"),
        cache_dir: formValue("cache_dir"),
        keep_page_markers: formChecked("keep_page_markers"),
        dry_run: formChecked("dry_run")
      };
      document.getElementById("start_btn").disabled = true;
      document.getElementById("status").textContent = "运行中";
      document.getElementById("done_text").textContent = "Running";
      document.getElementById("bar").style.width = "18%";
      const res = await fetch("/api/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      const data = await res.json();
      if (!data.ok) {
        appendLog("启动失败：" + data.error + "\n");
        document.getElementById("start_btn").disabled = false;
        return;
      }
      if (!polling) pollLogs();
    }

    async function pollLogs() {
      polling = true;
      const res = await fetch("/api/logs?since=" + logIndex);
      const data = await res.json();
      logIndex = data.next;
      for (const line of data.logs) appendLog(line);
      if (data.done) {
        document.getElementById("start_btn").disabled = false;
        document.getElementById("status").textContent = data.ok ? "完成" : "失败";
        document.getElementById("done_text").textContent = data.ok ? "Done" : "Error";
        document.getElementById("bar").style.width = data.ok ? "100%" : "55%";
        polling = false;
        return;
      }
      setTimeout(pollLogs, 800);
    }

    function appendLog(text) {
      const log = document.getElementById("log");
      log.textContent += text;
      log.scrollTop = log.scrollHeight;
    }
    function clearLog() {
      document.getElementById("log").textContent = "";
    }
    async function openOutputFolder() {
      await fetch("/api/open-output-folder", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({path: formValue("output_path")})});
    }
  </script>
</body>
</html>"""


def choose_path(kind: str) -> dict[str, str]:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "input":
            path = filedialog.askopenfilename(
                title="选择输入文件",
                filetypes=[
                    ("PDF / Text / Markdown", "*.pdf *.txt *.md *.markdown"),
                    ("PDF", "*.pdf"),
                    ("Text / Markdown", "*.txt *.md *.markdown"),
                    ("All files", "*.*"),
                ],
            )
            result = {"path": path}
            if path:
                p = Path(path)
                result["suggested_output"] = str(p.with_name(p.stem + ".zh.md"))
            return result
        if kind == "output":
            return {"path": filedialog.asksaveasfilename(title="选择输出文件", defaultextension=".md")}
        if kind == "glossary":
            return {"path": filedialog.askopenfilename(title="选择术语表/词典")}
        if kind == "cache":
            return {"path": filedialog.askdirectory(title="选择缓存目录")}
        return {"path": ""}
    finally:
        root.destroy()


def build_config(data: dict) -> tuple[Path, Path, translate_ai.Config]:
    input_path = Path(str(data.get("input_path", "")).strip())
    output_path = Path(str(data.get("output_path", "")).strip())
    if not input_path.exists():
        raise ValueError("请选择存在的输入文件")
    if not str(output_path):
        output_path = input_path.with_name(input_path.stem + ".zh.md")

    glossary_path = str(data.get("glossary_path", "")).strip()
    glossary = translate_ai.read_text(Path(glossary_path)) if glossary_path else ""

    provider = str(data.get("provider", "openai")).strip()
    settings = load_settings()
    saved_api_keys = settings.get("api_keys", {})
    api_key = str(data.get("api_key", "")).strip() or str(saved_api_keys.get(provider, "")).strip()
    base_url = str(data.get("base_url", "")).strip() or str(settings.get("base_url", "")).strip()
    remember_api_key = bool(data.get("remember_api_key", False))
    if api_key:
        os.environ[PROVIDER_KEY_ENV[provider]] = api_key
    if remember_api_key and api_key:
        save_api_key(provider, api_key, base_url if provider == "openai-compatible" else "")
    if provider == "openai-compatible":
        os.environ["OPENAI_COMPATIBLE_BASE_URL"] = base_url

    cfg = translate_ai.Config(
        provider=provider,
        model=str(data.get("model") or translate_ai.DEFAULT_MODELS[provider]).strip(),
        source_lang=str(data.get("source_lang") or "自动识别").strip(),
        target_lang=str(data.get("target_lang") or "简体中文").strip(),
        style=str(data.get("style") or "readable").strip(),
        quality=str(data.get("quality") or "standard").strip(),
        glossary=glossary,
        auto_glossaries=bool(data.get("auto_glossaries", True)),
        max_chars=int(data.get("max_chars") or 5000),
        context_chars=int(data.get("context_chars") or 3000),
        pdf_engine=str(data.get("pdf_engine") or "auto").strip(),
        pdf_quality=str(data.get("pdf_quality") or "balanced").strip(),
        keep_page_markers=bool(data.get("keep_page_markers", True)),
        glossary_limit=int(data.get("glossary_limit") or 80),
        retries=int(data.get("retries") or 3),
        sleep=float(data.get("sleep") or 1.0),
        cache_dir=Path(str(data.get("cache_dir") or ".translate_cache").strip()),
        dry_run=bool(data.get("dry_run", False)),
        generate_readable=True,
    )
    return input_path, output_path, cfg


def run_task(input_path: Path, output_path: Path, cfg: translate_ai.Config) -> None:
    writer = QueueWriter(STATE.log_queue)
    ok = False
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            translate_ai.translate_file(input_path, output_path, cfg)
        ok = True
    except SystemExit as exc:
        writer.write(f"\n运行失败：{exc}\n")
    except Exception:
        writer.write("\n运行失败：\n" + traceback.format_exc() + "\n")
    finally:
        with STATE.lock:
            STATE.running = False
            STATE.done = True
            STATE.ok = ok
            STATE.output_path = str(output_path)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *args) -> None:
        return None

    def send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            base_dir = Path(__file__).resolve().parent
            zh_hans_glossary = base_dir / "dictionaries" / "microsoft_terminology_zh_hans.txt"
            zh_hant_glossary = base_dir / "dictionaries" / "microsoft_terminology_zh_hant.txt"
            defaults = {
                "models": translate_ai.DEFAULT_MODELS,
                "cache_dir": str(base_dir / ".translate_cache"),
                "saved_api_keys": load_settings().get("api_keys", {}),
                "saved_base_url": load_settings().get("base_url", "https://example.com/v1"),
                "builtin_glossaries": {
                    "zh_hans": str(zh_hans_glossary) if zh_hans_glossary.exists() else "",
                    "zh_hant": str(zh_hant_glossary) if zh_hant_glossary.exists() else "",
                },
            }
            html = HTML.replace("__DEFAULTS__", json.dumps(defaults, ensure_ascii=False))
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/logs":
            while not STATE.log_queue.empty():
                STATE.push(STATE.log_queue.get())
            since = int(parse_qs(parsed.query).get("since", ["0"])[0])
            with STATE.lock:
                logs = STATE.logs[since:]
                next_index = len(STATE.logs)
                done = STATE.done
                ok = STATE.ok
            self.send_json({"logs": logs, "next": next_index, "done": done, "ok": ok})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/choose":
            kind = parse_qs(parsed.query).get("kind", [""])[0]
            self.send_json(choose_path(kind))
            return
        if parsed.path == "/api/start":
            with STATE.lock:
                if STATE.running:
                    self.send_json({"ok": False, "error": "已有任务正在运行"})
                    return
                STATE.logs = []
                STATE.done = False
                STATE.ok = False
                STATE.running = True
            try:
                input_path, output_path, cfg = build_config(self.read_json())
                thread = threading.Thread(target=run_task, args=(input_path, output_path, cfg), daemon=True)
                thread.start()
                self.send_json({"ok": True})
            except Exception as exc:
                with STATE.lock:
                    STATE.running = False
                    STATE.done = True
                    STATE.ok = False
                self.send_json({"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/open-output-folder":
            data = self.read_json()
            path = Path(str(data.get("path") or STATE.output_path or "."))
            folder = path.parent if path.suffix else path
            if folder.exists():
                os.startfile(str(folder))
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/clear-api-key":
            data = self.read_json()
            provider = str(data.get("provider") or "").strip()
            if provider not in PROVIDER_KEY_ENV:
                self.send_json({"ok": False, "error": "unknown provider"})
                return
            clear_api_key(provider)
            self.send_json({"ok": True})
            return
        self.send_error(404)


def find_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    port = find_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"AI translator web UI: {url}")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
