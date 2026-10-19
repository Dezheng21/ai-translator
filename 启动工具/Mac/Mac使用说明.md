# Mac 使用说明

目标：把整个 `AI翻译工具` 文件夹复制到 Mac 后，进入 `启动工具/Mac`，双击 `启动AI翻译工具.command`，自动准备环境并打开网页界面。

## 第一次使用

1. 把整个文件夹复制到 Mac。
2. 打开 `启动工具/Mac` 文件夹。
3. 双击 `启动AI翻译工具.command`。
4. 如果 macOS 提示不能打开，右键点击该文件，选择“打开”。
5. 如果提示没有执行权限，打开“终端”，进入 `启动工具/Mac` 后运行：

```bash
chmod +x 启动AI翻译工具.command
```

之后再双击即可。

## 自动安装内容

脚本会自动检查并安装：

- Homebrew
- Python
- Poppler，用于 PDF 转图片和文本处理
- Tesseract，用于扫描 PDF 的 OCR
- Python 依赖：`pdfplumber`、`pypdf`、`Pillow`

安装 Homebrew 或系统工具时，macOS 可能会要求输入电脑登录密码，这是正常现象。

## API Key

Mac 第一次启动时会重置旧配置，避免从 U 盘带入其它电脑的 API Key。

请在网页界面里重新填写 API Key。如果勾选“记住 API Key”，它只会保存在这台 Mac 的工具文件夹中。

## 日常使用

以后只需要双击：

```text
启动工具/Mac/启动AI翻译工具.command
```

浏览器会自动打开本地网页界面。
