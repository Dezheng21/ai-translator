# AI 翻译脚本使用说明

这个脚本用来把 `.txt` / `.md` / `.pdf` 文件分块翻译成目标语言，支持断点续跑缓存。

## 支持的 API

- `openai`：OpenAI Responses API，环境变量 `OPENAI_API_KEY`
- `anthropic`：Anthropic Messages API，环境变量 `ANTHROPIC_API_KEY`
- `gemini`：Google Gemini `generateContent` API，环境变量 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`
- `deepseek`：DeepSeek OpenAI-compatible chat completions，环境变量 `DEEPSEEK_API_KEY`
- `openai-compatible`：任意兼容 OpenAI `/chat/completions` 的接口

## 基本用法

```powershell
python .\translate_ai.py .\input.md -o .\output.zh.md
```

指定供应商和模型：

```powershell
$env:OPENAI_API_KEY="你的 key"
python .\translate_ai.py .\input.md -o .\output.zh.md --provider openai --model gpt-5.6-luna
```

```powershell
$env:ANTHROPIC_API_KEY="你的 key"
python .\translate_ai.py .\input.md -o .\output.zh.md --provider anthropic --model claude-sonnet-4-5
```

```powershell
$env:GEMINI_API_KEY="你的 key"
python .\translate_ai.py .\input.md -o .\output.zh.md --provider gemini --model gemini-3.5-flash
```

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
python .\translate_ai.py .\input.md -o .\output.zh.md --provider deepseek --model deepseek-chat
```

兼容 OpenAI 的第三方接口：

```powershell
$env:OPENAI_COMPATIBLE_API_KEY="你的 key"
$env:OPENAI_COMPATIBLE_BASE_URL="https://example.com/v1"
python .\translate_ai.py .\input.md -o .\output.zh.md --provider openai-compatible --model your-model-name
```

## 翻译风格

```powershell
python .\translate_ai.py .\input.md --style literal
python .\translate_ai.py .\input.md --style readable
python .\translate_ai.py .\input.md --style academic
python .\translate_ai.py .\input.md --style polished
```

- `literal`：更贴原文
- `readable`：忠实但更顺中文
- `academic`：学术中文，术语稳定
- `polished`：翻译后轻度润色

## 翻译水准和目标语言

```powershell
python .\translate_ai.py .\input.md -o .\output.zh.md --target-lang 简体中文 --quality high
python .\translate_ai.py .\input.md -o .\output.zh.md --target-lang 繁体中文 --quality publishable
```

水准选项：

- `fast`：快速水准，优先速度和基本准确
- `standard`：标准水准，兼顾准确、流畅和术语一致
- `high`：高质量水准，适合长文、论文、理论文本
- `publishable`：出版级水准，更重视中文表达和可归档质感

## 术语表

可以准备一个术语文件，例如 `glossary.md`：

```markdown
capital = 资本
field = 场域
habitus = 惯习
misrecognition = 误认
```

调用：

```powershell
python .\translate_ai.py .\input.md -o .\output.zh.md --glossary-file .\glossary.md --style academic
```

大词典也可以直接作为术语表传入。文件小于约 4000 字符时会整体注入；更大时会按当前分块自动匹配相关词条，并最多注入 `--glossary-limit` 条：

```powershell
python .\translate_ai.py .\paper.pdf -o .\paper.zh.md --glossary-file .\dictionary.tsv --glossary-limit 80
```

支持格式：

```text
source = target
source -> target
source,target
source<TAB>target
```

也支持 Markdown 表格：

```markdown
| source | target | note |
| --- | --- | --- |
| symbolic capital | 象征资本 | Bourdieu |
```

可用术语来源建议：

- CC-CEDICT：通用中英词典。
- OpenHowNet：中英词义/义原知识库。
- IATE：欧盟多语术语库。
- UNTERM：联合国多语术语库。
- Microsoft Terminology：技术与软件本地化术语。
- UMLS / MeSH：医学和生物医学术语；UMLS 需要注册和许可。

## 大文件参数

```powershell
python .\translate_ai.py .\input.md -o .\output.zh.md --max-chars 4000 --context-chars 3000 --sleep 2 --retries 5
```

- `--max-chars`：每块最大字符数，越小越稳，越大越省请求次数
- `--context-chars`：每个分块都会附带的文档上下文长度，用于长论文术语和语境一致；设为 `0` 可关闭
- `--sleep`：请求间隔，也作为重试退避的基础等待时间
- `--retries`：失败重试次数

## PDF 输入

```powershell
python .\translate_ai.py .\paper.pdf -o .\paper.zh.md --pdf-engine auto --style academic --quality high
```

PDF 提取方式：

- `auto`：依次尝试 `pdfplumber`、`pypdf`、`pdftotext`
- `pdfplumber`：对论文版式通常更稳，但需要安装 `pdfplumber`
- `pypdf`：纯 Python 提取，依赖较轻
- `pdftotext`：使用 Poppler 工具，适合已有 Poppler 的环境

默认会插入 `<!-- Page 1 -->` 这样的页码标记，方便回查原 PDF。命令行可用 `--no-page-markers` 关闭。

如果 PDF 是扫描件或图片版，普通文字提取会得到很少文本。脚本会在日志里提示，这种文件需要先 OCR。

## 长论文策略

脚本不会把整篇论文一次发给模型，而是：

1. 先从全文抽取题名/开头、摘要片段、章节线索，形成“文档上下文包”。
2. 再按段落切成多个分块，避免超过模型上下文。
3. 每个分块请求都会带上同一份上下文包，帮助术语、主题和论证线索保持一致。
4. 每个分块单独缓存，网络中断或额度不足后可以继续跑。

## 断点续跑

默认缓存目录是 `.translate_cache`。同一文本块、同一模型、同一风格、同一术语表再次运行时，会直接复用缓存。

如果想重翻，删除缓存目录：

```powershell
Remove-Item -Recurse -Force .\.translate_cache
```

## 先测试分块而不调用 API

```powershell
python .\translate_ai.py .\input.md -o .\dryrun.md --dry-run
```

## 官方接口参考

- OpenAI 官方文档推荐新项目使用 Responses API。
- Anthropic 官方文档使用 Messages API。
- Gemini 官方文档提供 `generateContent` 文本生成接口。
- DeepSeek 官方文档支持 OpenAI API 格式的 chat completions。
