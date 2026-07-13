# 词典与术语表说明

这个文件夹用于放翻译时可选的术语表。工具不会强制使用词典，因为不同领域的词典会影响译法。

## 已导入

- `microsoft_terminology_zh_hans.txt`：Microsoft Terminology Collection，英文到简体中文，适合软件、系统、技术、本地化相关文本。
- `microsoft_terminology_zh_hant.txt`：Microsoft Terminology Collection，英文到繁体中文，适合软件、系统、技术、本地化相关文本。
- `cedict_ts.u8`：CC-CEDICT 原始文件。
- `cc_cedict_zh_en.txt`：由 CC-CEDICT 转换出的中文到英文词典，适合中译英或中文词义辅助。
- `dictionary_registry.json`：内置词典注册表，记录每个词典的语言方向和领域。

界面里默认启用“自动选择内置词典”。工具会先判断语言方向，再判断领域，最后只把当前分块命中的词条交给 AI。

## 什么时候使用

- 技术论文、软件文档、计算机相关论文：建议使用 Microsoft 技术词典。
- 社会科学、人文理论、哲学论文：不建议默认使用技术词典，最好自己准备小型术语表。
- 医学、法律、欧盟政策、联合国文件：建议使用对应领域的专业术语库，不要混用技术词典。
- 中译英或中文文本解释：可以使用 CC-CEDICT。

## 自定义术语表格式

推荐使用一行一个术语：

```text
capital = 资本
field = 场域
habitus = 惯习
symbolic capital = 象征资本
```

也支持 CSV、TSV 和 Markdown 表格。大型词典不会整本塞给 AI，工具会按当前文本块自动挑出命中的词条。

## 需要手动下载的词典

- CC-CEDICT：通用中英词典。来源页面说明禁止自动脚本访问，所以没有替你自动抓取。你可以手动下载后放进这个文件夹。
- IATE：欧盟术语库。可按语言和领域导出，但通常需要在网页中选择和下载。
- UMLS / MeSH：医学和生物医学术语，UMLS 需要注册和许可证。
