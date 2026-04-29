import os
import re
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

"""
数据来源：https://github.com/szhuima/Laws
"""


class LawDataMaker:
    """法律数据制作器"""

    def __init__(self, input_dir: str = ".", output_dir: str = "data/law"):
        """
        初始化
        :param input_dir: 输入文件目录
        :param output_dir: 输出文件目录
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_articles_from_text(self, text: str) -> Dict[str, str]:
        """
        从文本中提取法条号和内容
        返回: {法条号: 内容}
        """
        articles = {}

        # 匹配法条号，如"第一条"、"第二条"等
        # 先找到所有法条号的位置
        article_pattern = r'第[一二三四五六七八九十百千万]+条'
        article_matches = list(re.finditer(article_pattern, text))

        if not article_matches:
            print("警告: 没有找到法条格式")
            return articles

        # 提取每个法条的内容
        for i, match in enumerate(article_matches):
            article_no = match.group(0)
            start_pos = match.end()

            # 确定下一个法条的开始位置
            if i < len(article_matches) - 1:
                end_pos = article_matches[i + 1].start()
            else:
                end_pos = len(text)

            # 提取内容
            content = text[start_pos:end_pos].strip()

            # 清理内容，移除"法宝联想"等无关信息
            content = re.sub(r'法宝联想.*?(?=第|$)', '', content, flags=re.DOTALL)
            # 移除章节标题
            content = re.sub(r'第[一二三四五六七八九十百千万]+章.*', '', content)
            # 清理多余的标点符号和空白
            content = content.strip()
            content = re.sub(r'^\s*[,，]+', '', content)
            content = self._clean_content(content)

            if article_no and content:
                articles[article_no] = content

        return articles

    def _clean_content(self, content: str) -> str:
        """清理法条内容"""
        # 移除多余的空格和空行
        lines = []
        for line in content.split('\n'):
            line = line.strip()
            if line:  # 只保留非空行
                lines.append(line)

        return '\n'.join(lines)

    def process_file(self, input_file: str, law_name: str = None, short_name: str = None) -> bool:
        """
        处理单个法律文件
        :param input_file: 输入文件名
        :param law_name: 法律名称
        :param short_name: 简称
        :return: 是否成功
        """
        input_path = self.input_dir / input_file

        if not input_path.exists():
            print(f"错误: 文件不存在 - {input_path}")
            return False

        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                text = f.read()

            print(f"正在处理: {input_file}")
            print(f"文件大小: {len(text)} 字符")

            # 提取元数据
            metadata = self.extract_metadata(text)

            # 检查时效性，如果是废止、失效或已被修改，则跳过处理
            effectiveness = metadata.get('effectiveness', '')
            # 使用更宽松的匹配方式，检查字符串是否包含关键词
            if any(keyword in effectiveness for keyword in ['废止', '失效', '已被修改']):
                print(f"跳过处理: {input_file} (时效性: {effectiveness})")
                return False

            # 提取法条
            articles = self.extract_articles_from_text(text)

            if not articles:
                print("警告: 没有提取到任何法条")
                return False

            # 生成输出数据
            if law_name is None:
                # 从文件名推断
                law_name = input_path.stem.replace('_', ' ').title()

            if short_name is None:
                # 提取可能的简称
                short_name = self._extract_short_name(law_name)

            output_data = {
                "law_name": law_name,
                "short_name": short_name,
                "url": metadata.get('url', ''),
                "cli": metadata.get('cli', ''),
                "effectiveness": metadata.get('effectiveness', ''),
                "publish_date": metadata.get('publish_date', ''),
                "implement_date": metadata.get('implement_date', ''),
                "articles": articles
            }

            # 生成输出文件名
            output_filename = f"{input_path.stem}.json"
            output_path = self.output_dir / output_filename

            # 保存
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            print(f"成功保存: {output_path}")
            print(f"   法条数量: {len(articles)}")
            print(f"   法律名称: {law_name}")
            print(f"   法律简称: {short_name}")
            print(f"   URL: {metadata.get('url', '未找到')}")
            print(f"   法宝引证码: {metadata.get('cli', '未找到')}")
            print(f"   时效性: {metadata.get('effectiveness', '未找到')}")
            print(f"   公布日期: {metadata.get('publish_date', '未找到')}")
            print(f"   实施日期: {metadata.get('implement_date', '未找到')}")

            # 显示样本
            print("\n样本法条:")
            for i, (article_no, content) in enumerate(list(articles.items())[:2]):
                preview = content[:60] + "..." if len(content) > 60 else content
                print(f"   {article_no}: {preview}")

            return True

        except Exception as e:
            print(f"处理文件时出错: {e}")
            return False

    def _extract_short_name(self, law_name: str) -> str:
        """从全名中提取简称"""
        # 常见法律简称规则
        patterns = [
            r'中华人民共和国(\w+)法',  # 中华人民共和国个人所得税法 -> 个人所得税法
            r'(\w+)法$',  # 民法典 -> 民法典
        ]

        for pattern in patterns:
            match = re.search(pattern, law_name)
            if match:
                return match.group(1) + "法"

        # 如果都不匹配，返回前4个字符
        return law_name[:4]

    def extract_metadata(self, text: str) -> Dict[str, str]:
        """提取元数据"""
        metadata = {}

        # 提取URL
        url_pattern = r'URL: (.+)'
        url_match = re.search(url_pattern, text)
        if url_match:
            metadata['url'] = url_match.group(1).strip()

        # 提取法宝引证码
        cli_pattern = r'【法宝引证码】(.+)'
        cli_match = re.search(cli_pattern, text)
        if cli_match:
            metadata['cli'] = cli_match.group(1).strip()

        # 提取时效性
        effectiveness_pattern = r'时效性：(.+)'
        effectiveness_match = re.search(effectiveness_pattern, text)
        if effectiveness_match:
            metadata['effectiveness'] = effectiveness_match.group(1).strip()

        # 提取公布日期
        publish_date_pattern = r'公布日期：(.+)'
        publish_date_match = re.search(publish_date_pattern, text)
        if publish_date_match:
            metadata['publish_date'] = publish_date_match.group(1).strip()

        # 提取实施日期
        implement_date_pattern = r'施行日期：(.+)'
        implement_date_match = re.search(implement_date_pattern, text)
        if implement_date_match:
            metadata['implement_date'] = implement_date_match.group(1).strip()

        return metadata

    def batch_process(self, file_pattern: str = "*.txt"):
        """批量处理文件"""
        input_files = list(self.input_dir.glob(file_pattern))

        if not input_files:
            print(f"在 {self.input_dir} 中没有找到 {file_pattern} 文件")
            return

        print(f"找到 {len(input_files)} 个文件需要处理")

        success_count = 0
        for input_file in input_files:
            print(f"\n{'=' * 50}")
            if self.process_file(input_file.name):
                success_count += 1

        print(f"\n{'=' * 50}")
        print(f"处理完成! 成功: {success_count}/{len(input_files)}")

        # 生成索引文件
        self.generate_index_file()

    def generate_index_file(self):
        """生成索引文件"""
        json_files = list(self.output_dir.glob("*.json"))

        if not json_files:
            return

        index_data = {}
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                law_name = data.get("law_name")
                short_name = data.get("short_name")

                if law_name:
                    index_data[json_file.stem] = {
                        "law_name": law_name,
                        "short_name": short_name,
                        "article_count": len(data.get("articles", {})),
                        "file": json_file.name
                    }
            except Exception as e:
                print(f"读取 {json_file} 时出错: {e}")

        index_path = self.output_dir / "index.json"
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)

        print(f"\n索引文件已生成: {index_path}")
        print(f"索引了 {len(index_data)} 个法律文件")


# 使用示例
if __name__ == "__main__":
    # 创建处理器
    maker = LawDataMaker(input_dir="data_doc/行政法规", output_dir="data/行政法规")

    # 批量处理当前目录下的所有txt和md文件
    # print("正在批量处理当前目录下的所有法律文件...")
    # 先处理txt文件
    maker.batch_process("*.txt")
    # 再处理md文件
    # maker.batch_process("*.md")

    # 如需处理单个文件，可取消下面的注释并修改文件名
    # maker.process_file(
    #     input_file="中华人民共和国安全生产法(2009修正) English已被修改.txt",
    #     law_name="中华人民共和国安全生产法",
    #     short_name="安全生产法"
    # )