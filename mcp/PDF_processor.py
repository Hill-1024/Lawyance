"""
这个PDF批注器提供了两个工具函数
pdf_commit_by_sentence：根据提供的文件路径，文本内容，坐标参数，对pdf文件进行批注
pdf_text_reader：解析pdf文件并返回json对象，内容为每句文本的坐标，给llm批注提供坐标参数
"""


import fitz  # PyMuPDF
import json
import re
import os
import sys
from pathlib import Path


class PDFTextExtractor:
    """
    PDF文本提取器
    从PDF中提取文本，按页分割，并根据标点分句，记录每个句子的末尾坐标
    """

    def __init__(self, pdf_path=None):
        """
        初始化PDF文本提取器

        Args:
            pdf_path (str, optional): PDF文件路径. 默认为None
        """
        self.pdf_path = pdf_path
        self.doc = None
        self.extracted_data = None

    def load_pdf(self, pdf_path=None):
        """
        加载PDF文件

        Args:
            pdf_path (str, optional): PDF文件路径. 如果为None，则使用初始化时指定的路径

        Returns:
            bool: 加载是否成功
        """
        if pdf_path:
            self.pdf_path = pdf_path

        if not self.pdf_path:
            print("错误: 未指定PDF文件路径")
            return False

        if not os.path.exists(self.pdf_path):
            print(f"错误: 文件不存在 - {self.pdf_path}")
            return False

        try:
            self.doc = fitz.open(self.pdf_path)
            print(f"成功加载PDF: {self.pdf_path}")
            print(f"PDF页数: {len(self.doc)}")
            return True
        except Exception as e:
            print(f"加载PDF失败: {str(e)}")
            return False

    def extract_sentences_with_coords(self, sentence_endings=r'[。！？；.!?;]+'):
        """
        从PDF中提取文本，按页分割，并根据标点分句，准确记录每个句子的末尾坐标

        Args:
            sentence_endings (str, optional): 用于分割句子的标点符号正则表达式

        Returns:
            list: 一个列表，每个元素是一个字典，代表一页
                  每页字典结构：{"page": 页码, "sentences": 句子列表}
                  每个句子字典结构：{"text": 句子文本, "end_coord": 末尾坐标元组 (x, y)}
        """
        if not self.doc:
            if not self.load_pdf():
                return None

        result = []

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]

            # 使用get_text("words")获取每个单词及其坐标
            # 格式: [(x0, y0, x1, y1, "word", block_no, line_no, word_no), ...]
            words = page.get_text("words")

            if not words:
                result.append({
                    "page": page_num + 1,
                    "sentences": []
                })
                continue

            # 将单词按行和位置排序
            # 先按y坐标（行）排序，再按x坐标（列）排序
            words.sort(key=lambda w: (w[1], w[0]))

            # 构建页面的完整文本和坐标映射
            page_text = ""
            word_coords = []  # 存储每个单词的坐标信息

            for word in words:
                word_text = word[4]
                # 单词的结束坐标（使用右下角坐标x1, y1）
                end_coord = (word[2], word[3])

                # 将单词文本添加到页面文本
                page_text += word_text
                # 记录单词结束坐标
                word_coords.append({
                    "text": word_text,
                    "end_index": len(page_text) - 1,  # 单词结束的字符索引
                    "end_coord": end_coord
                })

                # 在单词后添加空格（除非是中文标点）
                if not self._is_chinese_punctuation(word_text[-1] if word_text else ''):
                    page_text += " "

            if not page_text.strip():
                result.append({
                    "page": page_num + 1,
                    "sentences": []
                })
                continue

            # 分句
            # 使用正则表达式查找所有句子结束位置
            sentences = []
            sentence_start = 0

            # 找到所有句子结束符的位置
            index = 0
            for match in re.finditer(sentence_endings, page_text):
                sentence_end = match.end()  # 句子结束符后的位置

                # 获取句子文本
                sentence_text = page_text[sentence_start:sentence_end].strip()

                if sentence_text:
                    # 查找句子结束位置的坐标
                    # 找到句子中最后一个字符对应的单词坐标
                    sentence_end_char_index = sentence_end - 1
                    sentence_end_coord = self._find_coord_for_char_index(
                        sentence_end_char_index, word_coords)

                    sentences.append({
                        "text": sentence_text,
                        "end_coord": sentence_end_coord,
                        "index": index
                    })
                    index += 1
                sentence_start = sentence_end

            # 处理最后一个句子（如果没有以标点结束）
            if sentence_start < len(page_text):
                sentence_text = page_text[sentence_start:].strip()
                if sentence_text:
                    sentence_end_char_index = len(page_text) - 1
                    sentence_end_coord = self._find_coord_for_char_index(
                        sentence_end_char_index, word_coords)

                    sentences.append({
                        "text": sentence_text,
                        "end_coord": sentence_end_coord,
                        "index": index
                    })

            result.append({
                "page": page_num + 1,
                "sentences": sentences
            })

        self.extracted_data = result
        return result

    def _is_chinese_punctuation(self, char):
        """
        判断字符是否是中文标点

        Args:
            char (str): 字符

        Returns:
            bool: 是否是中文标点
        """
        if not char:
            return False

        # 中文标点Unicode范围
        chinese_punctuation_ranges = [
            (0x3000, 0x303F),  # 中文标点符号
            (0xFF00, 0xFFEF),  # 全角ASCII、全角标点
        ]

        char_code = ord(char)
        for start, end in chinese_punctuation_ranges:
            if start <= char_code <= end:
                return True

        return False

    def _find_coord_for_char_index(self, char_index, word_coords):
        """
        根据字符索引找到对应的单词坐标

        Args:
            char_index (int): 字符索引
            word_coords (list): 单词坐标列表

        Returns:
            tuple: 坐标 (x, y)
        """
        for word_info in word_coords:
            if char_index <= word_info["end_index"]:
                return word_info["end_coord"]

        # 如果没有找到，返回最后一个单词的坐标
        if word_coords:
            return word_coords[-1]["end_coord"]

        return (0.0, 0.0)

    def save_to_json(self, json_path="extracted_text.json"):
        """
        将提取的数据保存为JSON文件

        Args:
            json_path (str, optional): 输出JSON文件路径. 默认为"extracted_text.json"

        Returns:
            bool: 保存是否成功
        """
        if not self.extracted_data:
            print("错误: 没有数据可保存，请先执行extract_sentences_with_coords()")
            return False

        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(self.extracted_data, f, ensure_ascii=False, indent=2, default=str)
            print(f"结果已保存至: {json_path}")
            return True
        except Exception as e:
            print(f"保存JSON文件失败: {str(e)}")
            return False

    def get_extracted_data(self):
        """
        获取提取的数据

        Returns:
            list: 提取的数据
        """
        return self.extracted_data

    def print_summary(self, max_pages=3, max_sentences_per_page=5):
        """
        打印数据摘要

        Args:
            max_pages (int, optional): 最大打印页数. 默认为3
            max_sentences_per_page (int, optional): 每页最大打印句子数. 默认为5
        """
        if not self.extracted_data:
            print("错误: 没有数据可打印，请先执行extract_sentences_with_coords()")
            return

        print(f"总页数: {len(self.extracted_data)}")

        total_sentences = sum(len(page['sentences']) for page in self.extracted_data)
        print(f"总句子数: {total_sentences}")

        # 打印前几页的数据
        for i, page in enumerate(self.extracted_data[:max_pages]):
            print(f"\n{'=' * 60}")
            print(f"第 {page['page']} 页 (共 {len(page['sentences'])} 个句子):")
            for j, sentence in enumerate(page['sentences'][:max_sentences_per_page]):
                text_preview = sentence['text'][:100] + "..." if len(sentence['text']) > 100 else sentence['text']
                print(f"  句子 {j + 1}: {text_preview}")
                print(f"      末尾坐标: {sentence['end_coord']}")

            if len(page['sentences']) > max_sentences_per_page:
                print(f"  ... 还有 {len(page['sentences']) - max_sentences_per_page} 个句子未显示")

    def print_json(self):
        """
        以JSON格式打印完整数据
        """
        if not self.extracted_data:
            print("错误: 没有数据可打印，请先执行extract_sentences_with_coords()")
            return

        print(json.dumps(self.extracted_data, ensure_ascii=False, indent=2, default=str))

    def close(self):
        """
        关闭PDF文档
        """
        if self.doc:
            self.doc.close()
            self.doc = None

    def __del__(self):
        """
        析构函数，确保关闭PDF文档
        """
        self.close()


class PDFCommitor:
    def __init__(self, input_pdf_path, output_pdf_path=None):
        """
        初始化PDF批注器

        Args:
            input_pdf_path (str): 原始PDF文件路径
            output_pdf_path (str, optional): 输出PDF文件路径。默认为原始文件名后添加_gdutlawver
        """
        self.input_pdf_path = input_pdf_path

        if output_pdf_path is None:
            # 默认输出路径：原始文件名后添加_gdutlawver
            base_name, ext = os.path.splitext(input_pdf_path)
            if not base_name.endswith('_gdutlawver'):
                base_name = f"{base_name}_gdutlawver"
            self.output_pdf_path = f"{base_name}{ext}"
        else:
            self.output_pdf_path = output_pdf_path

        self.doc = None
        self.annotations = []

    def _open_pdf_document(self, file_path):
        """
        打开PDF文档，处理可能的加密状态

        Args:
            file_path (str): PDF文件路径

        Returns:
            fitz.Document: 打开的PDF文档对象
        """
        try:
            # 尝试以正常方式打开PDF
            doc = fitz.open(file_path)

            # 检查PDF是否加密
            if doc.needs_pass:
                print(f"警告: 文件 {file_path} 已加密，尝试使用空密码打开")
                # 尝试使用空密码解密
                if not doc.authenticate(""):
                    print("错误: PDF文件已加密且无法用空密码解密")
                    doc.close()
                    raise Exception("PDF文件已加密，需要密码")

            return doc
        except Exception as e:
            print(f"打开PDF文件失败: {str(e)}")
            raise

    def _save_pdf_document(self, doc, output_path, incremental=False):
        """
        保存PDF文档，处理可能的权限问题

        Args:
            doc (fitz.Document): PDF文档对象
            output_path (str): 输出文件路径
            incremental (bool): 是否使用增量保存模式

        Returns:
            bool: 保存是否成功
        """
        try:
            # 如果使用增量保存但文件不存在，则使用普通保存
            if incremental and not os.path.exists(output_path):
                incremental = False

            # 保存文档
            if incremental:
                # 使用增量保存，避免加密状态问题
                doc.save(output_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            else:
                # 普通保存，确保不加密
                doc.save(output_path, encryption=fitz.PDF_ENCRYPT_NONE)

            return True
        except Exception as e:
            print(f"保存PDF文件失败: {str(e)}")
            # 如果增量保存失败，尝试普通保存
            try:
                doc.save(output_path, encryption=fitz.PDF_ENCRYPT_NONE)
                return True
            except Exception as e2:
                print(f"普通保存也失败: {str(e2)}")
                return False

    def add_sticky_note_hover(self, note_text, position, page_num=0, icon='Note'):
        """
        添加鼠标悬停显示的便签注释

        参数：
        - note_text: 注释文本内容
        - position: (x, y) 图标位置坐标
        - page_num: 页码（从0开始）
        - icon: 图标类型，可选值：
            'Note' (默认) - 便签图标
            'Comment' - 评论图标
            'Help' - 帮助图标
            'Insert' - 插入图标
            'Key' - 钥匙图标
            'NewParagraph' - 新段落图标
            'Paragraph' - 段落图标
        """
        try:
            # 检查输出文件是否存在
            output_exists = os.path.exists(self.output_pdf_path)

            if output_exists:
                # 如果输出文件存在，在输出文件基础上添加批注
                print(f"在现有输出文件上添加批注: {self.output_pdf_path}")
                doc = self._open_pdf_document(self.output_pdf_path)
                incremental = True
            else:
                # 如果输出文件不存在，从原文件创建
                print(f"创建新的批注文件: {self.output_pdf_path}")
                doc = self._open_pdf_document(self.input_pdf_path)
                incremental = False

            # 检查页码是否有效
            if page_num >= len(doc) or page_num < 0:
                print(f"错误: 页码 {page_num} 超出范围，文档共有 {len(doc)} 页")
                doc.close()
                return False

            page = doc[page_num]

            # 添加文本注释（便签）
            annot = page.add_text_annot(position, note_text, icon=icon)

            # 设置注释属性
            annot.set_info(
                title="便签注释",  # 标题
                content=note_text,  # 内容
                subject="用户注释"  # 主题
            )

            # 设置颜色（边框颜色）
            annot.set_colors(stroke=(1, 1, 0))  # 黄色边框

            # 设置作者
            info = annot.info
            info["title"] = "工大法智"
            annot.set_info(info)

            # 更新注释
            annot.update()

            # 记录注释信息
            self.annotations.append({
                "page": page_num + 1,
                "position": position,
                "text": note_text
            })

            # 保存文档
            success = self._save_pdf_document(doc, self.output_pdf_path, incremental)

            # 关闭文档
            doc.close()

            if success:
                print(f"✅ 成功添加便签注释到 {self.output_pdf_path}")
                print(f"   页码: {page_num + 1}")
                print(f"   位置: {position}")
                print(f"   文本: {note_text[:50]}{'...' if len(note_text) > 50 else ''}")
                print(f"   当前累计注释数: {len(self.annotations)}")
                return True
            else:
                print(f"❌ 添加便签注释失败")
                return False

        except Exception as e:
            print(f"❌ 添加批注时发生错误: {str(e)}")
            return False

    def get_output_path(self):
        """获取输出文件路径"""
        return self.output_pdf_path

    def get_annotation_count(self):
        """获取已添加的注释数量"""
        return len(self.annotations)

    def get_annotations(self):
        """获取注释列表"""
        return self.annotations

    def close(self):
        """关闭文档"""
        if self.doc:
            self.doc.close()
            self.doc = None

    def __del__(self):
        """析构函数，确保关闭文档"""
        self.close()


# Tools
def pdf_text_reader(pdf_path):
    """
    读取PDF文本并返回JSON格式字符串

    Args:
        pdf_path (str): PDF文件路径

    Returns:
        str: JSON格式的文本数据
    """
    extractor = PDFTextExtractor(pdf_path)
    data = extractor.extract_sentences_with_coords()
    extractor.close()

    if data is None:
        return json.dumps({"error": "无法提取PDF文本"}, ensure_ascii=False, indent=2)

    return json.dumps(data, ensure_ascii=False, indent=2, default=str)

def pdf_commit(pdf_path, note_text, position=(100, 100), page_num=0, icon='Note', output_path=None):
    """
    在PDF文件上添加批注

    Args:
        pdf_path (str): PDF文件路径
        note_text (str): 批注文本
        position (tuple): 批注位置 (x, y)
        page_num (int): 页码（从0开始）
        icon (str): 图标类型
        output_path (str, optional): 输出文件路径

    Returns:
        tuple: (是否成功, 输出文件路径)
    """
    try:
        # 创建PDFCommitor实例
        if output_path:
            commitor = PDFCommitor(pdf_path, output_path)
        else:
            commitor = PDFCommitor(pdf_path)

        # 添加批注
        result = commitor.add_sticky_note_hover(
            note_text=note_text,
            position=position,
            page_num=page_num,
            icon=icon
        )

        output_path = commitor.get_output_path()
        commitor.close()

        return result, output_path
    except Exception as e:
        print(f"❌ pdf_commit 函数执行失败: {str(e)}")
        return False, None


def pdf_commit_by_sentence(pdf_path, note_text, page_index=0, sentence_index=0, icon='Note', output_path=None):
    """
    在指定句子位置添加批注

    Args:
        pdf_path (str): PDF文件路径
        note_text (str): 批注文本
        page_index (int): 页码索引（从0开始）
        sentence_index (int): 句子索引（从0开始）
        icon (str): 图标类型
        output_path (str, optional): 输出文件路径

    Returns:
        tuple: (是否成功, 输出文件路径)
    """
    extractor = PDFTextExtractor(pdf_path)
    sentence_data = extractor.extract_sentences_with_coords()
    try:
        # 如果是JSON字符串，先解析
        if isinstance(sentence_data, str):
            try:
                data = json.loads(sentence_data)
            except json.JSONDecodeError:
                print("❌ 错误: sentence_data 是无效的JSON字符串")
                return False, None
        else:
            data = sentence_data

        # 检查数据格式
        if not isinstance(data, list) or len(data) == 0:
            print("❌ 错误: sentence_data 格式不正确，应为列表")
            return False, None

        # 检查页码是否有效
        if page_index >= len(data) or page_index < 0:
            print(f"❌ 错误: 页码索引 {page_index} 超出范围，总页数: {len(data)}")
            return False, None

        page_data = data[page_index]

        # 检查句子索引是否有效
        if "sentences" not in page_data or sentence_index >= len(page_data["sentences"]) or sentence_index < 0:
            print(f"❌ 错误: 句子索引 {sentence_index} 超出范围")
            if "sentences" in page_data:
                print(f"    第 {page_index + 1} 页共有 {len(page_data['sentences'])} 个句子")
            return False, None

        # 获取句子坐标
        sentence = page_data["sentences"][sentence_index]
        position = sentence["end_coord"]

        print(f"📄 第 {page_data['page']} 页，第 {sentence_index + 1} 个句子")
        print(f"📍 位置坐标: {position}")
        print(f"📝 句子内容: {sentence['text'][:100]}{'...' if len(sentence['text']) > 100 else ''}")

        # 调用批注函数
        return pdf_commit(
            pdf_path=pdf_path,
            note_text=note_text,
            position=position,
            page_num=page_data["page"] - 1,  # 转换为0-based索引
            icon=icon,
            output_path=output_path
        )
    except Exception as e:
        print(f"❌ 根据句子添加批注失败: {str(e)}")
        return False, None

# 最简测试用例
if __name__ == "__main__":
    print(pdf_text_reader("sample.pdf"))
    pdf_commit_by_sentence(
        "sample.pdf",
        "我是天才",
        4,
        0
    )
# 测试用例

# if __name__ == "__main__":
#     # 测试1: 解析PDF并查看数据
#     print("=" * 60)
#     print("测试1: 解析PDF文件")
#     print("=" * 60)
#
#     pdf_path = "sample.pdf"
#
#     if not os.path.exists(pdf_path):
#         print(f"❌ 测试文件 {pdf_path} 不存在，请先准备一个PDF文件")
#         # 创建一个简单的测试文件
#         print("⚠️ 正在创建测试PDF文件...")
#         try:
#             import fitz
#
#             doc = fitz.open()
#             page = doc.new_page()
#
#             # 添加多个句子，每个句子在不同位置
#             page.insert_text((50, 50), "这是第一个句子。")
#             page.insert_text((50, 100), "这是第二个句子，包含一些文本。")
#             page.insert_text((50, 150), "第三个句子在这里！")
#             page.insert_text((50, 200), "第四个句子是一个问句？")
#             page.insert_text((50, 250), "第五个句子有不同的坐标。")
#
#             doc.save(pdf_path)
#             doc.close()
#             print(f"✅ 已创建测试PDF文件: {pdf_path}")
#         except:
#             print("❌ 无法创建测试PDF文件，请手动准备一个PDF文件")
#             sys.exit(1)
#
#     # 解析PDF
#     extractor = PDFTextExtractor(pdf_path)
#     data = extractor.extract_sentences_with_coords()
#
#     if data:
#         print("✅ PDF解析成功")
#         print(f"📊 解析数据统计:")
#         print(f"   总页数: {len(data)}")
#
#         for i, page in enumerate(data):
#             print(f"\n   第 {page['page']} 页: {len(page['sentences'])} 个句子")
#             for j, sentence in enumerate(page['sentences']):
#                 print(f"     句子 {j + 1}: {sentence['text']}")
#                 print(f"       末尾坐标: {sentence['end_coord']}")
#
#         # 保存为JSON文件
#         extractor.save_to_json("extracted_text.json")
#     else:
#         print("❌ PDF解析失败")
#
#     extractor.close()
#
#     # 测试2: 添加批注
#     print("\n" + "=" * 60)
#     print("测试2: 根据句子坐标添加批注")
#     print("=" * 60)
#
#     if data and len(data) > 0:
#         # 检查是否有第二页
#         if len(data) >= 3 and len(data[2]["sentences"]) > 0:
#             # 为第二页的每个句子添加批注
#             page_data = data[2]  # 注意：索引1表示第二页
#             print(f"🔍 查询第二页信息:")
#             print(f"   页码: {page_data['page']}")
#             print(f"   句子数: {len(page_data['sentences'])}")
#
#             for i, sentence in enumerate(page_data["sentences"]):
#                 note_text = f"这是对第{i + 1}个句子的批注"
#                 success, output = pdf_commit_by_sentence(
#                     pdf_path=pdf_path,
#                     note_text=note_text,
#                     page_index=2,  # 修改这里：0表示第一页，1表示第二页
#                     sentence_index=i,
#                     icon='Note'
#                 )
#
#                 if success:
#                     print(f"✅ 成功为第{i + 1}个句子添加批注")
#                     print(f"   句子: {sentence['text'][:50]}...")
#                     print(f"   坐标: {sentence['end_coord']}")
#                 else:
#                     print(f"❌ 为第{i + 1}个句子添加批注失败")
#         else:
#             print("⚠️ 没有第二页或第二页没有句子")
#
#         # 同时也可以查询第一页
#         if len(data[0]["sentences"]) > 0:
#             print(f"\n🔍 同时查询第一页信息:")
#             page_data = data[0]  # 索引0表示第一页
#             print(f"   页码: {page_data['page']}")
#             print(f"   句子数: {len(page_data['sentences'])}")
#
#     print("\n" + "=" * 60)
#     print("测试完成!")
#     print("=" * 60)