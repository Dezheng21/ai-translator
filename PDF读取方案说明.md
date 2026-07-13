# PDF 读取与校验方案

PDF 读取不能做到绝对保证，因为 PDF 保存的是页面绘制结果，不一定保存正确的阅读顺序。但工具现在会在翻译前做质量校验，避免把明显错误的文本送去翻译。

## 默认方案

界面里的“PDF 读取方式”默认是 `auto`，会尝试：

- `pdfplumber`
- `pypdf`
- `pdftotext`

然后生成一个 `*.pdf_quality.md` 报告，检查：

- 每页提取字符数是否过少
- 是否有乱码或替换字符
- 是否有异常长词、异常控制字符
- 多个提取引擎之间是否大体一致
- 是否疑似扫描件，需要 OCR

“PDF 文本校验”建议保持“平衡校验”。如果报告分数低，工具会停止翻译。

## 可选 GitHub/开源方案

### Docling

适合：通用论文、复杂版面、表格、公式、OCR、后续 AI 处理。

安装：

```powershell
pip install docling
```

安装后在界面里把“PDF 读取方式”改为 `docling`。

### Marker

适合：PDF 转 Markdown、公式、表格、页眉页脚清理、需要高质量 Markdown 的论文。

安装：

```powershell
pip install marker-pdf
```

安装后在界面里把“PDF 读取方式”改为 `marker`。Marker 第一次运行可能下载模型，速度会慢一些。

### GROBID

适合：学术论文结构化解析，尤其标题、作者、摘要、正文、参考文献、引用上下文、TEI XML。

GROBID 通常需要以本地服务方式运行，不适合直接塞进轻量桌面脚本。后续如果你需要，我可以给工具增加“连接本地 GROBID 服务”的选项。

### MinerU

适合：复杂文档、扫描件、公式、表格、阅读顺序，需要更重的 OCR/版面模型。

MinerU 能力强，但安装和模型依赖更重。建议在大量扫描论文或公式密集论文时再接入。

## 建议工作流

1. 普通数字版论文：先用 `auto + 平衡校验`。
2. 分数低或排版复杂：改用 `docling`。
3. 需要更好 Markdown、公式和表格：试 `marker`。
4. 扫描件或 OCR 很差：用 Marker 强制 OCR、MinerU，或先用 OCRmyPDF/Tesseract 做 OCR。
5. 文献元数据和参考文献特别重要：考虑 GROBID。

