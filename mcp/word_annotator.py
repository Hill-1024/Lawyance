"""
这是一个word文档解析器，提供了两个工具
word_reader:根据文件路径读取docx文档，并返回一个json格式数据，包含段落索引和内容
word_writer:根据段落索引和文本内容，对文档进行批注
每次批注不会改动原本的文件，会生成一个后缀加上_gdutlawver的文件
每次批注会优先读取现有的_gdutlawver的文件，实现多个批注
"""




import os
from os.path import exists

from docx import Document
from docx.shared import Inches
import docx

class WordAnnotator:
    def __init__(self, file_path):
        if not exists(file_path):
            print(f"未找到文件{file_path}")
            return
        self.file_path = file_path
        self.doc = Document(file_path)
    def reader(self):
        """读取文本，返回json格式输出"""
        word_list = []
        for i, paragraph in enumerate(self.doc.paragraphs):
            if not paragraph.text:
                continue

            para = {
                "index": i,
                "text": paragraph.text,
            }
            word_list.append(para)
        return word_list
    def writer(self, index, text, output_path=None):
        if output_path is None:
            base_name, ext = os.path.splitext(self.file_path)
            output_path = f"{base_name}_gdutlawver{ext}"

        if not exists(output_path):
            doc = Document(self.file_path)
        else:
            doc = Document(output_path)
        print("正在批注……")
        comment = doc.add_comment(
            runs=doc.paragraphs[index].runs,
            text=text,
            author="工大法智",
            initials="GDUTlaw",
        )
        doc.save(output_path)
        return True
def word_reader(file_path):
    word = WordAnnotator(file_path)
    words = word.reader()
    # print(words)
    return words
def word_writer(file_path, index, text, output_path=None):
    word = WordAnnotator(file_path)
    word.writer(index, text, output_path)
    return True

# 最简测试用例
if __name__ == "__main__":
    words = word_reader("sample.docx")
    print(words)
    # words = word.writer(10, "这是一只inu")
    word_writer("sample.docx",10, "测试你是不是吗喽")
