#!/usr/bin/env python3
"""Simple desktop GUI for translate_ai.py."""

from __future__ import annotations

import contextlib
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

import translate_ai


PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
}


class QueueWriter:
    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        self.log_queue = log_queue

    def write(self, text: str) -> int:
        if text:
            self.log_queue.put(text)
        return len(text)

    def flush(self) -> None:
        return None


class TranslateApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("AI 翻译工具")
        self.root.geometry("860x720")
        self.root.minsize(760, 620)

        base_dir = Path(__file__).resolve().parent
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self.input_path = StringVar()
        self.output_path = StringVar()
        self.glossary_path = StringVar()
        self.cache_dir = StringVar(value=str(base_dir / ".translate_cache"))
        self.provider = StringVar(value="openai")
        self.model = StringVar(value=translate_ai.DEFAULT_MODELS["openai"])
        self.api_key = StringVar()
        self.base_url = StringVar(value="https://example.com/v1")
        self.source_lang = StringVar(value="英文")
        self.target_lang = StringVar(value="简体中文")
        self.style = StringVar(value="readable")
        self.quality = StringVar(value="standard")
        self.max_chars = StringVar(value="5000")
        self.context_chars = StringVar(value="3000")
        self.glossary_limit = StringVar(value="80")
        self.pdf_engine = StringVar(value="auto")
        self.pdf_quality = StringVar(value="balanced")
        self.keep_page_markers = BooleanVar(value=False)
        self.retries = StringVar(value="3")
        self.sleep = StringVar(value="1.0")
        self.dry_run = BooleanVar(value=False)

        self._build_ui()
        self._poll_log_queue()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(10, weight=1)

        title = ttk.Label(main, text="AI 翻译工具", font=("Microsoft YaHei UI", 18, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self._file_row(main, 1, "输入文件", self.input_path, self._choose_input)
        self._file_row(main, 2, "输出文件", self.output_path, self._choose_output)
        self._file_row(main, 3, "术语表", self.glossary_path, self._choose_glossary, optional=True)

        provider_box = ttk.LabelFrame(main, text="模型与 API", padding=12)
        provider_box.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        for col in range(4):
            provider_box.columnconfigure(col, weight=1)

        ttk.Label(provider_box, text="供应商").grid(row=0, column=0, sticky="w")
        provider_combo = ttk.Combobox(
            provider_box,
            textvariable=self.provider,
            state="readonly",
            values=list(translate_ai.DEFAULT_MODELS.keys()),
        )
        provider_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 8))
        provider_combo.bind("<<ComboboxSelected>>", self._provider_changed)

        ttk.Label(provider_box, text="模型").grid(row=0, column=1, sticky="w")
        ttk.Entry(provider_box, textvariable=self.model).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 8)
        )

        ttk.Label(provider_box, text="API Key（不保存）").grid(row=0, column=2, sticky="w")
        ttk.Entry(provider_box, textvariable=self.api_key, show="*").grid(
            row=1, column=2, sticky="ew", padx=(0, 8), pady=(4, 8)
        )

        ttk.Label(provider_box, text="兼容接口 Base URL").grid(row=0, column=3, sticky="w")
        ttk.Entry(provider_box, textvariable=self.base_url).grid(
            row=1, column=3, sticky="ew", pady=(4, 8)
        )

        options = ttk.LabelFrame(main, text="翻译设置", padding=12)
        options.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        for col in range(6):
            options.columnconfigure(col, weight=1)

        ttk.Label(options, text="源语言").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.source_lang,
            values=["自动识别", "英文", "中文", "日文", "韩文", "法文", "德文", "西班牙文"],
        ).grid(
            row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 8)
        )
        ttk.Label(options, text="目标语言").grid(row=0, column=1, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.target_lang,
            values=["简体中文", "繁体中文", "英文", "日文", "韩文", "法文", "德文", "西班牙文"],
        ).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 8)
        )
        ttk.Label(options, text="风格").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.style,
            state="readonly",
            values=sorted(translate_ai.STYLE_INSTRUCTIONS.keys()),
        ).grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(4, 8))
        ttk.Label(options, text="翻译水准").grid(row=0, column=3, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.quality,
            state="readonly",
            values=sorted(translate_ai.QUALITY_INSTRUCTIONS.keys()),
        ).grid(row=1, column=3, sticky="ew", padx=(0, 8), pady=(4, 8))

        ttk.Label(options, text="每块字符").grid(row=2, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.max_chars).grid(
            row=3, column=0, sticky="ew", padx=(0, 8), pady=(4, 8)
        )
        ttk.Label(options, text="重试次数").grid(row=2, column=1, sticky="w")
        ttk.Entry(options, textvariable=self.retries).grid(
            row=3, column=1, sticky="ew", padx=(0, 8), pady=(4, 8)
        )
        ttk.Label(options, text="请求间隔").grid(row=2, column=2, sticky="w")
        ttk.Entry(options, textvariable=self.sleep).grid(
            row=3, column=2, sticky="ew", padx=(0, 8), pady=(4, 8)
        )

        ttk.Label(options, text="缓存目录").grid(row=2, column=3, sticky="w")
        ttk.Entry(options, textvariable=self.cache_dir).grid(
            row=3, column=3, columnspan=2, sticky="ew", padx=(0, 8), pady=(4, 8)
        )
        ttk.Button(options, text="选择", command=self._choose_cache).grid(
            row=3, column=5, sticky="ew", pady=(4, 8)
        )

        long_doc = ttk.LabelFrame(main, text="PDF 与长论文", padding=12)
        long_doc.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        for col in range(4):
            long_doc.columnconfigure(col, weight=1)
        ttk.Label(long_doc, text="PDF 提取方式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            long_doc,
            textvariable=self.pdf_engine,
            state="readonly",
            values=["auto", "pdfplumber", "pypdf", "pdftotext", "docling", "marker"],
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 0))
        ttk.Label(long_doc, text="上下文包字符").grid(row=0, column=1, sticky="w")
        ttk.Entry(long_doc, textvariable=self.context_chars).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 0)
        )
        ttk.Label(long_doc, text="术语注入上限").grid(row=0, column=2, sticky="w")
        ttk.Entry(long_doc, textvariable=self.glossary_limit).grid(
            row=1, column=2, sticky="ew", padx=(0, 8), pady=(4, 0)
        )
        ttk.Checkbutton(
            long_doc,
            text="PDF 页码标记",
            variable=self.keep_page_markers,
        ).grid(row=1, column=3, sticky="w", padx=(0, 8), pady=(4, 0))
        ttk.Label(
            long_doc,
            text="长文会自动分块，并给每块附带题名/摘要/章节线索。",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Checkbutton(main, text="测试模式（不调用 API）", variable=self.dry_run).grid(
            row=7, column=0, sticky="w", pady=(12, 0)
        )

        button_bar = ttk.Frame(main)
        button_bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        button_bar.columnconfigure(0, weight=1)
        self.start_button = ttk.Button(button_bar, text="开始翻译", command=self._start)
        self.start_button.grid(row=0, column=1, sticky="e")
        ttk.Button(button_bar, text="打开输出文件夹", command=self._open_output_folder).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
        )

        ttk.Label(main, text="运行日志").grid(row=9, column=0, sticky="w", pady=(12, 4))
        self.log_text = self._make_log(main)
        self.log_text.grid(row=10, column=0, columnspan=3, sticky="nsew")

    def _make_log(self, parent: ttk.Frame):
        import tkinter as tk

        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word", height=14)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_frame = frame
        return frame

    def _append_log(self, text: str) -> None:
        text_widget = self.log_frame.winfo_children()[0]
        text_widget.insert("end", text)
        text_widget.see("end")

    def _file_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: StringVar,
        command,
        optional: bool = False,
    ) -> None:
        ttk.Label(parent, text=label + ("（可选）" if optional else "")).grid(
            row=row, column=0, sticky="w", pady=4
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Button(parent, text="选择", command=command).grid(row=row, column=2, sticky="ew", pady=4)

    def _provider_changed(self, _event=None) -> None:
        provider = self.provider.get()
        self.model.set(translate_ai.DEFAULT_MODELS[provider])

    def _choose_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择输入文件",
            filetypes=[
                ("PDF / Text / Markdown", "*.pdf *.txt *.md *.markdown"),
                ("PDF", "*.pdf"),
                ("Text / Markdown", "*.txt *.md *.markdown"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.input_path.set(path)
        if not self.output_path.get():
            input_path = Path(path)
            self.output_path.set(str(input_path.with_name(input_path.stem + ".zh.md")))

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择输出文件",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.output_path.set(path)

    def _choose_glossary(self) -> None:
        path = filedialog.askopenfilename(
            title="选择术语表",
            filetypes=[("Text / Markdown", "*.txt *.md *.markdown"), ("All files", "*.*")],
        )
        if path:
            self.glossary_path.set(path)

    def _choose_cache(self) -> None:
        path = filedialog.askdirectory(title="选择缓存目录")
        if path:
            self.cache_dir.set(path)

    def _open_output_folder(self) -> None:
        path_text = self.output_path.get().strip()
        folder = Path(path_text).parent if path_text else Path.cwd()
        if folder.exists():
            os.startfile(str(folder))
        else:
            messagebox.showwarning("提示", "输出文件夹还不存在。")

    def _validate(self) -> tuple[Path, Path, Path | None, translate_ai.Config] | None:
        input_text = self.input_path.get().strip()
        output_text = self.output_path.get().strip()
        input_path = Path(input_text)
        output_path = Path(output_text)
        glossary_text = self.glossary_path.get().strip()
        glossary_path = Path(glossary_text) if glossary_text else None

        if not input_text or not input_path.exists():
            messagebox.showerror("输入错误", "请选择存在的输入文件。")
            return None
        if not output_text:
            messagebox.showerror("输入错误", "请选择输出文件。")
            return None
        if glossary_path and not glossary_path.exists():
            messagebox.showerror("输入错误", "术语表文件不存在。")
            return None

        try:
            max_chars = int(self.max_chars.get())
            context_chars = int(self.context_chars.get())
            glossary_limit = int(self.glossary_limit.get())
            retries = int(self.retries.get())
            sleep = float(self.sleep.get())
        except ValueError:
            messagebox.showerror("输入错误", "每块字符、上下文包字符、术语注入上限、重试次数、请求间隔必须是数字。")
            return None
        if max_chars < 500:
            messagebox.showerror("输入错误", "每块字符建议至少 500。")
            return None
        if context_chars < 0:
            messagebox.showerror("输入错误", "上下文包字符不能小于 0。")
            return None
        if glossary_limit < 0:
            messagebox.showerror("输入错误", "术语注入上限不能小于 0。")
            return None

        provider = self.provider.get()
        key = self.api_key.get().strip()
        if key:
            os.environ[PROVIDER_KEY_ENV[provider]] = key
        if provider == "openai-compatible":
            os.environ["OPENAI_COMPATIBLE_BASE_URL"] = self.base_url.get().strip()

        glossary = translate_ai.read_text(glossary_path) if glossary_path else ""
        cfg = translate_ai.Config(
            provider=provider,
            model=self.model.get().strip() or translate_ai.DEFAULT_MODELS[provider],
            source_lang=self.source_lang.get().strip() or "原文",
            target_lang=self.target_lang.get().strip() or "简体中文",
            style=self.style.get(),
            quality=self.quality.get(),
            glossary=glossary,
            auto_glossaries=True,
            max_chars=max_chars,
            context_chars=context_chars,
            pdf_engine=self.pdf_engine.get(),
            pdf_quality=self.pdf_quality.get(),
            keep_page_markers=self.keep_page_markers.get(),
            glossary_limit=glossary_limit,
            retries=retries,
            sleep=sleep,
            cache_dir=Path(self.cache_dir.get().strip() or ".translate_cache"),
            dry_run=self.dry_run.get(),
        )
        return input_path, output_path, glossary_path, cfg

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "翻译正在进行中。")
            return
        validated = self._validate()
        if validated is None:
            return
        input_path, output_path, _glossary_path, cfg = validated
        self.start_button.configure(state="disabled")
        self._append_log("\n=== 开始翻译 ===\n")
        self.worker = threading.Thread(
            target=self._run_translation,
            args=(input_path, output_path, cfg),
            daemon=True,
        )
        self.worker.start()

    def _run_translation(self, input_path: Path, output_path: Path, cfg: translate_ai.Config) -> None:
        writer = QueueWriter(self.log_queue)
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
            self.log_queue.put("__DONE_OK__" if ok else "__DONE_ERROR__")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == "__DONE_OK__":
                    self.start_button.configure(state="normal")
                    messagebox.showinfo("完成", "翻译完成。")
                elif item == "__DONE_ERROR__":
                    self.start_button.configure(state="normal")
                    messagebox.showerror("失败", "翻译失败，请查看运行日志。")
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main() -> None:
    root = Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except Exception:
        pass
    app = TranslateApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
