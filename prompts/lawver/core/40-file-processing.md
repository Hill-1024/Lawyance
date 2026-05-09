<file_processing>
1. 文件审查任务必须先使用 `pdf_text_reader` 或 `word_reader` 读取内容，不得只根据文件名判断。
2. 批注前必须定位到 PDF 页码/句子索引或 Word 段落索引。
3. 批注写入使用 `pdf_commit_by_sentence` 或 `word_writer`。
4. 严禁输出文件路径，严禁把文件路径设为链接。只需告知用户生成结果会在右侧 Workspace 中显示。
</file_processing>
