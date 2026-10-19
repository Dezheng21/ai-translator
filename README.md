# AI 翻译工具

把 PDF、Markdown、TXT 文件分块交给大模型翻译的本地工具，适合论文、长文档和技术资料。有图形界面，也能在命令行批量使用；支持断点续跑、术语表和 PDF 提取质量校验。

## 特点

- **多家模型可选**：OpenAI、Anthropic、Google Gemini、DeepSeek，以及任意兼容 OpenAI `/chat/completions` 的接口。
- **长文档友好**：按段落自动分块，翻译结果缓存在本地，中断后可以从上次位置继续。
- **PDF 校验**：先用 pdfplumber / pypdf / pdftotext 提取并对比，生成质量报告；疑似扫描件或乱码时会停下来，不把错误文本送去翻译。
- **术语表**：内置 Microsoft 技术术语和 CC-CEDICT 中英词典，按语言方向和领域自动挑选；也可以导入自己的术语表（TXT / CSV / TSV / Markdown 表格）。
- **翻译风格与水准**：`readable` / `academic` 两种风格，`fast` / `high` / `publishable` 三档精细度，目标语言可自定义。

## 快速开始

需要 Python 3。

**Windows**：双击 `启动工具/Windows/启动AI翻译工具.bat`。如果中文文件名的启动器闪退，改用同目录的 `start_ai_translator_modern.bat`；`start_ai_translator.bat` 是旧版 Tkinter 界面。

**macOS**：双击 `启动工具/Mac/启动AI翻译工具.command`，首次运行会自动安装依赖，详见 `启动工具/Mac/Mac使用说明.md`。

**命令行**：

```bash
export OPENAI_API_KEY="你的 key"
python translate_ai.py input.pdf -o output.zh.md --provider openai
```

先只看分块结果、不调用 API：

```bash
python translate_ai.py input.md --dry-run
```

## API Key

可以用环境变量（`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`、`DEEPSEEK_API_KEY` 等），也可以在界面里勾选“记住 API Key”。后者以明文保存在本机的 `.translator_settings.json`，该文件已加入 `.gitignore`，不会被提交。

## 文件说明

| 文件 | 内容 |
| --- | --- |
| `translate_ai.py` | 核心翻译逻辑与命令行入口 |
| `translate_ai_web.py` | 现代网页界面（默认启动） |
| `translate_ai_gui.py` | 旧版 Tkinter 界面 |
| `import_cedict.py` / `import_microsoft_tbx.py` | 把原始词典转换成工具使用的术语表 |
| `dictionaries/` | 内置术语表与注册表，说明见 `dictionaries/README.md` |
| `启动工具/` | Windows 与 macOS 启动器 |
| `translate_ai_README.md` | 命令行参数完整说明 |
| `AI翻译工具_桌面版说明.md` | 图形界面使用说明 |
| `PDF读取方案说明.md` | PDF 提取与 OCR 方案对比 |

## 词典来源与许可

- CC-CEDICT：[MDBG](https://www.mdbg.net/chinese/dictionary?page=cc-cedict)，CC BY-SA 4.0。
- Microsoft Terminology Collection：微软语言门户提供的术语集，使用需遵守微软的许可条款。

原始大文件（`MicrosoftTermCollection/`、`cedict_ts.u8`）不在仓库中，需要时手动下载后用上面的导入脚本转换。
