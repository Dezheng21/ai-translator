# AI 翻译工具桌面版

Windows 用户双击 `启动工具\Windows\启动AI翻译工具.bat` 即可打开图形界面。

如果中文文件名启动器闪退，请双击 `启动工具\Windows\start_ai_translator_modern.bat`。这个版本使用英文文件名和纯 ASCII 内容，更适合 Windows 批处理。

如果你更想用旧版 Tkinter 窗口，可以双击 `启动工具\Windows\start_ai_translator.bat`。

Mac 用户请进入 `启动工具/Mac`，双击 `启动AI翻译工具.command`，首次运行会自动安装依赖。详见 `启动工具/Mac/Mac使用说明.md`。

## 使用步骤

1. 选择输入文件：支持 `.pdf`、`.txt`、`.md`、`.markdown`。
2. 选择输出文件：建议保存为 `.zh.md`。
3. 选择供应商：OpenAI、Anthropic、Gemini、DeepSeek，或 OpenAI-compatible。
4. 填入 API Key：如果勾选“记住 API Key”，会保存到工具文件夹里的本机设置文件，下次自动填入。
5. 选择目标语言：例如简体中文、繁体中文、英文、日文、韩文，也可以直接输入自定义语言。
6. 选择翻译风格：`readable` 更顺中文，`academic` 更适合论文和理论文本。
7. 选择翻译水准：`fast` 更快，`high` 更细，`publishable` 更适合保存或发布。
8. 点击“开始翻译”。

## API Key 保存

现代界面支持按供应商保存 API Key。勾选“记住 API Key（保存在本机）”后，工具会把 Key 写入：

```text
AI翻译工具\.translator_settings.json
```

这个文件只在本机使用，不会上传。它是明文保存；如果这台电脑多人共用，建议不要勾选，或者用界面里的“清除当前供应商 Key”删除已保存的 Key。

## 风格、水准、目标语言

- 目标语言：决定译文输出语言，可以使用预设，也可以手动输入，如“韩语敬语体”“台湾繁体中文”等。
- 风格：决定译文气质和句法取向，例如直译、顺读、学术、润色。
- 水准：决定模型处理细致程度。水准越高，提示词会越强调术语一致、逻辑梳理和中文表达质量。

## PDF 与长论文

主界面里的“任务类型”已经内置常用方案：

- 论文 PDF（推荐）：适合大多数论文 PDF。
- 论文文本 / Markdown：适合已经提取好的正文。
- 快速普通翻译：适合短文、普通材料或草稿。

下面这些高级设置一般不用改：

- PDF 提取方式：建议先用 `auto`。它会依次尝试 `pdfplumber`、`pypdf`、`pdftotext`。
- PDF 页码标记：默认开启，会在译文中保留 `<!-- Page 1 -->` 之类标记，方便回查原文页码。
- 上下文包字符：长论文不会一次性发给 AI，而是分块翻译。工具会把题名、摘要片段、章节线索作为上下文附到每一块里，减少术语漂移。
- 如果是扫描件 PDF，普通提取可能拿不到文字。日志会提示“extracted very little text”，这种情况需要先 OCR。

## 术语表 / 词典

术语表文件可以很小，也可以很大。小术语表会整体交给模型；大词典会先在当前分块中匹配，只把命中的术语注入提示词，避免撑爆上下文。

推荐格式：

```text
capital = 资本
field = 场域
habitus = 惯习
symbolic capital = 象征资本
```

也支持 CSV/TSV 或 Markdown 表格：

```markdown
| source | target | note |
| --- | --- | --- |
| misrecognition | 误认 | Bourdieu 术语 |
```

可参考的外部术语来源：

- CC-CEDICT：中英通用词典，适合普通词汇，不是论文专业术语库。
- OpenHowNet：中英词义/义原知识库，适合辅助理解词义。
- IATE：欧盟多语术语库，适合法律、政策、公共领域文本。
- UNTERM：联合国多语术语库，适合国际组织、政治、法律、发展议题。
- Microsoft Terminology：微软术语库，适合技术、本地化、软件相关文本。
- UMLS / MeSH：医学、生物医学领域更专业，但 UMLS 需要注册和许可。

## OpenAI-compatible 怎么填

如果你使用通义、Moonshot、智谱、硅基流动等兼容 OpenAI 格式的服务：

- 供应商选择 `openai-compatible`
- API Key 填该平台的 key
- Base URL 填该平台的 `/v1` 地址，例如 `https://example.com/v1`
- 模型名填该平台提供的模型 ID

## 缓存

工具会把已翻译的文本块缓存到 `.translate_cache`。同一文本、同一模型、同一风格再次运行时会复用缓存，方便断点续跑。

如果想全部重翻，删除 `.translate_cache` 文件夹即可。

## 测试模式

勾选“测试模式（不调用 API）”可以先检查分块和输出路径，不会消耗 API 额度。
