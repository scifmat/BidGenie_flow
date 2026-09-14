#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidGenie Flow - Markdown 转 Word 脚本（阶段八）

功能：
1. 解析 Markdown 文件（标题、段落、图片、表格、列表、代码块、引用、行内格式）
2. 应用样式模板（标题字体、正文字体、表格样式、图片样式、图题样式）
3. 实现标题自动编号：
   - 默认（--auto-numbering）：Word 真正的多级自动编号，通过 numbering.xml
     定义多级列表并绑定到 Heading 2~6 样式。增删章节时 Word 自动重算编号。
   - 兼容（--no-auto-numbering）：硬编码拼接编号字符串到标题文本。
4. 处理图片插入（居中、宽度80%页面、图题居中）
5. 处理表格样式（表头加粗灰底、内容宋体五号）

编号方案（多级自动编号模式）：
    H1（文档标题）→ 无编号
    H2 → 第N章       （ilvl=0, lvlText="第%1章"）
    H3 → N.M          （ilvl=1, lvlText="%1.%2"）
    H4 → N.M.K        （ilvl=2, lvlText="%1.%2.%3"）
    H5 → N.M.K.L      （ilvl=3, lvlText="%1.%2.%3.%4"）
    H6 → N.M.K.L.J    （ilvl=4, lvlText="%1.%2.%3.%4.%5"）

命令行接口：
    python md_to_docx.py \\
        --input <merged_proposal.md 路径> \\
        --output <输出 .docx 路径> \\
        --project-name <项目名称> \\
        --images-dir <images 目录路径> \\
        [--auto-numbering | --no-auto-numbering]

依赖库：
- python-docx: pip install python-docx
"""

import os
import sys
import re
import struct
import argparse
from typing import Optional, List, Tuple


# ==========================================================
# 常量定义
# ==========================================================

# 字号映射（中文字号 → pt）
FONT_SIZE_MAP = {
    '二号': 22,
    '三号': 16,
    '小三号': 15,
    '四号': 14,
    '小四号': 12,
    '五号': 10.5,
    '小五号': 9,
}

# 标题字号映射
HEADING_FONT_SIZE = {
    1: '二号',
    2: '三号',
    3: '小三号',
    4: '四号',
    5: '小四号',
    6: '小四号',
}

# 标题对齐方式
HEADING_ALIGNMENT = {
    1: 'center',
    2: 'left',
    3: 'left',
    4: 'left',
    5: 'left',
    6: 'left',
}

# 默认正文字体
DEFAULT_BODY_FONT = '宋体'
DEFAULT_HEADING_FONT = '黑体'
DEFAULT_CODE_FONT = 'Consolas'

# 正文字体颜色（黑色，统一用于标题和正文，覆盖 Word 默认蓝色主题色）
BODY_COLOR = (0, 0, 0)

# 图片默认宽度（厘米）
DEFAULT_IMAGE_WIDTH_CM = 15

# 页面可用宽度（A4 宽度 21cm - 左右页边距 3.18*2 = 14.64cm）
PAGE_CONTENT_WIDTH_CM = 21.0 - 3.18 * 2

# 图片最大高度（A4 高度 29.7cm - 上下页边距 2.54*2 - 图题预留 2cm ≈ 22.6cm）
# 超过此高度的图片按高度等比缩放，避免单图占满整页或溢出
MAX_IMAGE_HEIGHT_CM = 22.0

# 首行缩进（厘米，约2字符）
FIRST_LINE_INDENT_CM = 0.74

# 行距倍数
LINE_SPACING = 1.5

# 表格灰底颜色
TABLE_HEADER_FILL = 'D9D9D9'

# Markdown 标题正则
HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$')

# 图片引用正则 ![alt](path)
IMAGE_PATTERN = re.compile(r'!\[(.+?)\]\((.+?)\)')

# 表格行正则
TABLE_ROW_PATTERN = re.compile(r'^\|(.+)\|$')
TABLE_SEPARATOR_PATTERN = re.compile(r'^\|[\s\-:|]+\|$')

# 有序列表正则
ORDERED_LIST_PATTERN = re.compile(r'^(\d+)\.\s+(.+)$')
# 无序列表正则
UNORDERED_LIST_PATTERN = re.compile(r'^[-*]\s+(.+)$')

# 引用正则
QUOTE_PATTERN = re.compile(r'^>\s*(.*)$')

# 图题/表题正则（斜体行）
CAPTION_PATTERN = re.compile(r'^\*(图|表)\s+([\d\-]+)\s+(.+?)\*$')

# 行内格式：加粗、斜体、删除线、行内代码
INLINE_FORMAT_PATTERN = re.compile(
    r'(\*\*(.+?)\*\*'        # **加粗**
    r'|\*([^*]+?)\*'          # *斜体*
    r'|~~(.+?)~~'             # ~~删除线~~
    r'|`([^`]+?)`)'           # `行内代码`
)

# 表格标题正则（粗体行）
TABLE_TITLE_PATTERN = re.compile(r'^\*\*(表)\s+([\d\-]+)\s+(.+?)\*\*$')


def _get_png_size(img_path: str) -> Optional[Tuple[int, int]]:
    """
    读取 PNG 图片原始尺寸（宽, 高），无需 Pillow 依赖。
    PNG 文件头第 16-24 字节为 IHDR 块的宽高（4 字节大端无符号整数）。

    Args:
        img_path: PNG 文件路径

    Returns:
        (width, height) 像素元组，读取失败返回 None
    """
    try:
        with open(img_path, 'rb') as f:
            header = f.read(24)
            # PNG 签名 8 字节 + IHDR 长度 4 字节 + 类型 4 字节 = 16 字节偏移
            if len(header) < 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
                return None
            width, height = struct.unpack('>II', header[16:24])
            return (width, height)
    except Exception:
        return None


class HeadingNumberer:
    """标题自动编号器"""

    def __init__(self):
        # 各层级计数器（index 1~6 对应标题1~6）
        self.counters = [0] * 7

    def get_number(self, level: int) -> Optional[str]:
        """
        获取指定层级的编号

        Args:
            level: 标题层级（1~6）

        Returns:
            str: 编号字符串，标题1 返回 None（无编号）
        """
        if level < 1 or level > 6:
            return None

        self.counters[level] += 1
        # 重置下级计数器
        for i in range(level + 1, 7):
            self.counters[i] = 0

        if level == 1:
            return None  # 标题1 无编号（文档标题）
        elif level == 2:
            return f"第{self.counters[2]}章"
        elif level == 3:
            return f"{self.counters[2]}.{self.counters[3]}"
        elif level == 4:
            return f"{self.counters[2]}.{self.counters[3]}.{self.counters[4]}"
        elif level == 5:
            return f"{self.counters[2]}.{self.counters[3]}.{self.counters[4]}.{self.counters[5]}"
        elif level == 6:
            return (f"{self.counters[2]}.{self.counters[3]}.{self.counters[4]}."
                    f"{self.counters[5]}.{self.counters[6]}")
        return None


class MdToDocxConverter:
    """Markdown 转 Word 转换器"""

    def __init__(self, images_dir: str, project_name: str = '',
                 auto_numbering: bool = True):
        """
        初始化转换器

        Args:
            images_dir: 图片目录路径
            project_name: 项目名称（用于文档属性）
            auto_numbering: 是否启用 Word 真正的多级自动编号
                True  - 标题段落仅写入纯文本，编号由 numbering.xml 通过
                        Heading 样式自动渲染，增删章节时 Word 自动重编号
                False - 兼容旧行为：在标题文本前硬编码拼接编号字符串
        """
        try:
            from docx import Document
            from docx.shared import Pt, Cm, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.enum.table import WD_TABLE_ALIGNMENT
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
        except ImportError as e:
            raise ImportError(
                "python-docx 库未安装，请执行: pip install python-docx\n"
                f"详细错误: {str(e)}"
            )

        # 保存导入的模块
        self.Document = Document
        self.Pt = Pt
        self.Cm = Cm
        self.RGBColor = RGBColor
        self.WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH
        self.WD_TABLE_ALIGNMENT = WD_TABLE_ALIGNMENT
        self.qn = qn
        self.OxmlElement = OxmlElement

        self.doc = Document()
        self.images_dir = os.path.abspath(images_dir) if images_dir else ''
        self.project_name = project_name
        self.auto_numbering = auto_numbering
        self.heading_numberer = HeadingNumberer()
        # 多级列表 numId（启用自动编号后由 _setup_multilevel_numbering 写入）
        self._multilevel_num_id: Optional[int] = None

        # 设置文档属性
        if project_name:
            self.doc.core_properties.title = project_name + '_技术方案'
            self.doc.core_properties.author = 'BidGenie Flow'

        # 设置默认样式
        self._setup_default_styles()
        self._setup_page()

        # 启用 Word 多级自动编号：定义 numbering.xml 多级列表并绑定到 Heading 2~6 样式
        if self.auto_numbering:
            self._setup_multilevel_numbering()

    def _setup_default_styles(self):
        """设置文档默认样式"""
        # 正文样式
        style = self.doc.styles['Normal']
        style.font.name = DEFAULT_BODY_FONT
        style.font.size = self.Pt(FONT_SIZE_MAP['小四号'])
        # 中文字体设置
        style.element.rPr.rFonts.set(self.qn('w:eastAsia'), DEFAULT_BODY_FONT)

    def _setup_page(self):
        """设置页面（A4 纸张，标准页边距）"""
        for section in self.doc.sections:
            # A4 纸张大小
            section.page_width = self.Cm(21.0)
            section.page_height = self.Cm(29.7)
            # 页边距（上下 2.54cm，左右 3.18cm）
            section.top_margin = self.Cm(2.54)
            section.bottom_margin = self.Cm(2.54)
            section.left_margin = self.Cm(3.18)
            section.right_margin = self.Cm(3.18)

    # ==========================================================
    # 多级自动编号（Word native multilevel list numbering）
    # ==========================================================
    #
    # 实现原理：
    # 1. 在 numbering.xml 中定义一个多级列表（w:abstractNum + w:num）
    #    - 每一级 w:lvl 包含 w:numFmt（编号格式）和 w:lvlText（编号模板）
    #    - 模板使用 %1, %2, ... 占位符引用对应级别的计数器
    # 2. 将 Heading 2~6 样式绑定到这个多级列表
    #    - 在样式的 w:pPr 中加入 <w:numPr><w:ilvl/><w:numId/></w:numPr>
    # 3. 添加标题时只写入纯文本，编号由 Word 渲染时自动生成
    #
    # 层级映射：
    #   H1（文档标题）→ 不绑定列表，无编号
    #   H2 → ilvl=0 → 第N章       lvlText="第%1章"
    #   H3 → ilvl=1 → N.M          lvlText="%1.%2"
    #   H4 → ilvl=2 → N.M.K        lvlText="%1.%2.%3"
    #   H5 → ilvl=3 → N.M.K.L      lvlText="%1.%2.%3.%4"
    #   H6 → ilvl=4 → N.M.K.L.J    lvlText="%1.%2.%3.%4.%5"
    #
    # 优势：用户在 Word 中增删/移动章节时，所有编号自动重算，无需手动修改

    # WordprocessingML 命名空间
    _W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    # 多级列表各级配置：(ilvl, lvlText, font_size_pt)
    # font_size_pt 与 HEADING_FONT_SIZE 保持一致：
    #   H2(三号=16) H3(小三号=15) H4(四号=14) H5(小四号=12) H6(小四号=12)
    _MULTILEVEL_LVL_CONFIGS = [
        (0, '第%1章', 16),
        (1, '%1.%2', 15),
        (2, '%1.%2.%3', 14),
        (3, '%1.%2.%3.%4', 12),
        (4, '%1.%2.%3.%4.%5', 12),
    ]

    def _setup_multilevel_numbering(self):
        """
        创建 Word 多级列表编号定义并绑定到 Heading 2~6 样式。

        实现真正的多级自动编号，便于用户在 Word 中增删章节时编号自动更新。
        若文档已存在 numbering.xml，则在其中追加新的多级列表定义；
        若不存在（python-docx 默认模板通常包含），则尝试创建。
        """
        from docx.oxml import parse_xml

        # 获取或创建 numbering part
        numbering_elem = self._get_or_create_numbering_element()
        if numbering_elem is None:
            # 创建失败，回退到硬编码模式
            self.auto_numbering = False
            print('[警告] 无法获取/创建 numbering.xml，回退到硬编码编号模式',
                  file=sys.stderr)
            return

        # 确定下一个可用的 abstractNumId
        existing_abstract_nums = numbering_elem.findall(self.qn('w:abstractNum'))
        new_abstract_id = 0
        for abs_num in existing_abstract_nums:
            try:
                aid = int(abs_num.get(self.qn('w:abstractNumId')))
                if aid >= new_abstract_id:
                    new_abstract_id = aid + 1
            except (TypeError, ValueError):
                continue

        # 确定下一个可用的 numId（numId=0 表示"无编号"，从 1 开始）
        existing_nums = numbering_elem.findall(self.qn('w:num'))
        new_num_id = 0
        for num in existing_nums:
            try:
                nid = int(num.get(self.qn('w:numId')))
                if nid >= new_num_id:
                    new_num_id = nid + 1
            except (TypeError, ValueError):
                continue
        if new_num_id == 0:
            new_num_id = 1

        # 构建 abstractNum XML
        # 每个 w:lvl 包含：
        #   - w:rPr：编号字符格式（字体、字号、颜色、非斜体），与标题文字保持一致
        #   - w:suff="space"：编号与标题之间仅一个空格（距离为 0，无制表符）
        # OOXML CT_Lvl 子元素顺序：start → numFmt → lvlText → lvlJc → suff → pPr → rPr
        abstract_xml_parts = [
            f'<w:abstractNum xmlns:w="{self._W_NS}" '
            f'w:abstractNumId="{new_abstract_id}">',
            '<w:multiLevelType w:val="multilevel"/>',
        ]
        for ilvl, lvl_text, font_size_pt in self._MULTILEVEL_LVL_CONFIGS:
            # 字号转 half-points（OOXML 用 half-points 表示字号）
            sz_half_pt = int(font_size_pt * 2)
            abstract_xml_parts.append(
                f'<w:lvl w:ilvl="{ilvl}">'
                f'<w:start w:val="1"/>'
                f'<w:numFmt w:val="decimal"/>'
                f'<w:lvlText w:val="{lvl_text}"/>'
                f'<w:lvlJc w:val="left"/>'
                # 编号后跟空格（非制表符），编号与标题距离为 0
                f'<w:suff w:val="space"/>'
                f'<w:pPr>'
                f'<w:ind w:left="0" w:firstLine="0"/>'
                f'</w:pPr>'
                # 编号字符格式：黑体、加粗、非斜体、黑色、与标题同字号
                f'<w:rPr>'
                f'<w:rFonts w:ascii="{DEFAULT_HEADING_FONT}" '
                f'w:eastAsia="{DEFAULT_HEADING_FONT}" '
                f'w:hAnsi="{DEFAULT_HEADING_FONT}"/>'
                f'<w:b/>'
                f'<w:i w:val="false"/>'
                f'<w:color w:val="000000"/>'
                f'<w:sz w:val="{sz_half_pt}"/>'
                f'<w:szCs w:val="{sz_half_pt}"/>'
                f'</w:rPr>'
                f'</w:lvl>'
            )
        abstract_xml_parts.append('</w:abstractNum>')
        abstract_elem = parse_xml(''.join(abstract_xml_parts))

        # abstractNum 必须在 num 之前（OOXML schema 顺序要求）
        first_num = numbering_elem.find(self.qn('w:num'))
        if first_num is not None:
            first_num.addprevious(abstract_elem)
        else:
            numbering_elem.append(abstract_elem)

        # 创建 num 元素引用 abstractNum
        num_xml = (
            f'<w:num xmlns:w="{self._W_NS}" w:numId="{new_num_id}">'
            f'<w:abstractNumId w:val="{new_abstract_id}"/>'
            f'</w:num>'
        )
        num_elem = parse_xml(num_xml)
        numbering_elem.append(num_elem)

        # 绑定 Heading 2~6 样式到多级列表
        # H2 → ilvl=0, H3 → ilvl=1, ..., H6 → ilvl=4
        for level in range(2, 7):
            ilvl = level - 2
            self._bind_heading_style_to_numbering(level, new_num_id, ilvl)

        self._multilevel_num_id = new_num_id

    def _get_or_create_numbering_element(self):
        """获取或创建 numbering.xml 的根元素，失败返回 None"""
        # python-docx Document.part 提供 numbering_part 属性
        # 默认模板（default.docx）通常已包含 numbering.xml
        try:
            numbering_part = self.doc.part.numbering_part
            return numbering_part.element
        except (KeyError, AttributeError):
            pass

        # 兜底：手动创建 numbering part
        try:
            from docx.parts.numbering import NumberingPart
            from docx.opc.packuri import PackURI
            from docx.opc.constants import RELATIONSHIP_TYPE as RT
            from docx.oxml import parse_xml

            partname = PackURI('/word/numbering.xml')
            content_type = (
                'application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.numbering+xml'
            )
            numbering_elem = parse_xml(
                f'<w:numbering xmlns:w="{self._W_NS}"/>'
            )
            numbering_part = NumberingPart.new(
                partname, content_type, numbering_elem,
                self.doc.part.package
            )
            self.doc.part.relate_to(numbering_part, RT.NUMBERING)
            return numbering_part.element
        except Exception as e:
            print(f'[警告] 创建 numbering.xml 失败: {e}', file=sys.stderr)
            return None

    def _bind_heading_style_to_numbering(self, level: int, num_id: int,
                                          ilvl: int):
        """
        将指定 Heading 样式绑定到多级列表。

        Args:
            level: 标题级别（2~6）
            num_id: 多级列表的 numId
            ilvl: 多级列表中的层级索引（0~4）
        """
        style_name = f'Heading {level}'
        try:
            style = self.doc.styles[style_name]
        except KeyError:
            return

        style_elem = style.element
        ppr = style_elem.find(self.qn('w:pPr'))
        if ppr is None:
            ppr = self.OxmlElement('w:pPr')
            style_elem.append(ppr)

        # 移除已有的 numPr（避免重复绑定导致冲突）
        existing = ppr.find(self.qn('w:numPr'))
        if existing is not None:
            ppr.remove(existing)

        # 添加 numPr：<w:numPr><w:ilvl/><w:numId/></w:numPr>
        num_pr = self.OxmlElement('w:numPr')
        ilvl_elem = self.OxmlElement('w:ilvl')
        ilvl_elem.set(self.qn('w:val'), str(ilvl))
        num_id_elem = self.OxmlElement('w:numId')
        num_id_elem.set(self.qn('w:val'), str(num_id))
        num_pr.append(ilvl_elem)
        num_pr.append(num_id_elem)
        ppr.append(num_pr)

    def _set_run_font(self, run, font_name: str = DEFAULT_BODY_FONT,
                       size: Optional[int] = None, bold: bool = False,
                       italic: bool = False, strike: bool = False,
                       color: Optional[Tuple[int, int, int]] = None):
        """设置 run 的字体属性"""
        run.font.name = font_name
        # 中文字体设置（必须同时设置 eastAsia）
        run.element.rPr.rFonts.set(self.qn('w:eastAsia'), font_name)

        if size is not None:
            run.font.size = self.Pt(size)
        if bold:
            run.bold = True
        # italic 显式设置（False 也需写入，覆盖样式层斜体如 Heading 4 的 <w:i/>）
        run.italic = bool(italic)
        if strike:
            run.font.strike = True
        if color:
            run.font.color.rgb = self.RGBColor(*color)

    def _set_cell_shading(self, cell, fill_color: str):
        """设置单元格底纹颜色"""
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = self.OxmlElement('w:shd')
        shd.set(self.qn('w:val'), 'clear')
        shd.set(self.qn('w:color'), 'auto')
        shd.set(self.qn('w:fill'), fill_color)
        tc_pr.append(shd)

    def _set_paragraph_shading(self, paragraph, fill_color: str):
        """
        设置段落底纹（背景色）。

        用于代码块/终端块的视觉区分，按 OOXML schema 顺序将 w:shd
        插入到 w:pBdr 之后、w:ind 之前。
        """
        pPr = paragraph._p.get_or_add_pPr()
        # 移除已有 shd
        existing = pPr.find(self.qn('w:shd'))
        if existing is not None:
            pPr.remove(existing)

        shd = self.OxmlElement('w:shd')
        shd.set(self.qn('w:val'), 'clear')
        shd.set(self.qn('w:color'), 'auto')
        shd.set(self.qn('w:fill'), fill_color)

        # shd 必须在 pBdr 之后、ind 之前
        pBdr = pPr.find(self.qn('w:pBdr'))
        if pBdr is not None:
            pBdr.addnext(shd)
        else:
            # 没有 pBdr，插入到 pPr 第一个子元素之前（保持顺序靠前）
            if len(pPr) > 0:
                pPr[0].addprevious(shd)
            else:
                pPr.append(shd)

    def _set_paragraph_border(self, paragraph, color: str,
                                sz: str = '4', space: str = '4'):
        """
        设置段落四边边框（细边框）。

        用于代码块/终端块的视觉区分，按 OOXML schema 顺序将 w:pBdr
        插入到 pPr 较前位置（在 w:shd 之前）。

        Args:
            paragraph: docx 段落对象
            color: 边框颜色（十六进制 RGB，如 'CCCCCC'）
            sz: 边框宽度（1/8 pt 单位，'4' = 0.5pt）
            space: 边框与文本距离（1/8 pt 单位）
        """
        pPr = paragraph._p.get_or_add_pPr()
        # 移除已有 pBdr
        existing = pPr.find(self.qn('w:pBdr'))
        if existing is not None:
            pPr.remove(existing)

        pBdr = self.OxmlElement('w:pBdr')
        for side in ['top', 'left', 'bottom', 'right']:
            border = self.OxmlElement(f'w:{side}')
            border.set(self.qn('w:val'), 'single')
            border.set(self.qn('w:sz'), sz)
            border.set(self.qn('w:space'), space)
            border.set(self.qn('w:color'), color)
            pBdr.append(border)

        # pBdr 必须在 shd 之前，插入到 pPr 最前
        if len(pPr) > 0:
            pPr[0].addprevious(pBdr)
        else:
            pPr.append(pBdr)

    def _compute_image_size(self, img_path: str) -> Tuple[float, float]:
        """
        基于页面可用宽度和图片原始比例智能计算图片显示尺寸（等比缩放）。
        算法：以页面可用宽度为上限，按原始宽高比等比缩放；
        若缩放后高度超过最大高度，则以最大高度为基准反向等比缩放。

        Args:
            img_path: 图片文件路径

        Returns:
            (width_cm, height_cm) 厘米元组
        """
        # 默认宽度（无法读取尺寸时使用）
        default_w = min(DEFAULT_IMAGE_WIDTH_CM, PAGE_CONTENT_WIDTH_CM)

        orig = _get_png_size(img_path)
        if not orig:
            # 非 PNG 或读取失败，使用默认宽度（Word 自动按比例缩放高度）
            return (default_w, 0)

        orig_w, orig_h = orig
        if orig_w <= 0 or orig_h <= 0:
            return (default_w, 0)

        # 以页面可用宽度为上限等比缩放
        target_w = min(default_w, PAGE_CONTENT_WIDTH_CM)
        target_h = target_w * orig_h / orig_w

        # 若高度超过最大高度，以高度为基准反向缩放
        if target_h > MAX_IMAGE_HEIGHT_CM:
            target_h = MAX_IMAGE_HEIGHT_CM
            target_w = target_h * orig_w / orig_h

        return (target_w, target_h)

    def convert(self, md_content: str):
        """
        转换 Markdown 内容为 Word

        Args:
            md_content: Markdown 文本内容
        """
        lines = md_content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 空行
            if not stripped:
                i += 1
                continue

            # HTML 注释行（如 <!-- chart_type: flowchart -->），跳过不转换
            if stripped.startswith('<!--') and stripped.endswith('-->'):
                i += 1
                continue

            # 标题
            heading_match = HEADING_PATTERN.match(stripped)
            if heading_match:
                self._add_heading(heading_match)
                i += 1
                continue

            # 表格标题（粗体行：**表 X-Y-Z-N 名称**）
            table_title_match = TABLE_TITLE_PATTERN.match(stripped)
            if table_title_match:
                self._add_table_title(table_title_match)
                i += 1
                continue

            # 图题/表题（斜体行：*图 X-Y-Z-N 名称*）
            caption_match = CAPTION_PATTERN.match(stripped)
            if caption_match:
                self._add_caption(caption_match)
                i += 1
                continue

            # 图片
            image_match = IMAGE_PATTERN.match(stripped)
            if image_match:
                self._add_image(image_match)
                i += 1
                continue

            # 表格（需要至少 2 行才识别为表格）
            if stripped.startswith('|') and i + 1 < len(lines) and lines[i + 1].strip().startswith('|'):
                i = self._add_table(lines, i)
                continue

            # 代码块
            if stripped.startswith('```'):
                i = self._add_code_block(lines, i)
                continue

            # 引用
            quote_match = QUOTE_PATTERN.match(stripped)
            if quote_match:
                self._add_quote(quote_match.group(1))
                i += 1
                continue

            # 有序列表
            ordered_match = ORDERED_LIST_PATTERN.match(stripped)
            if ordered_match:
                self._add_list_item(ordered_match.group(2), ordered=True,
                                    number=ordered_match.group(1))
                i += 1
                continue

            # 无序列表
            unordered_match = UNORDERED_LIST_PATTERN.match(stripped)
            if unordered_match:
                self._add_list_item(unordered_match.group(1), ordered=False)
                i += 1
                continue

            # 普通正文段落
            self._add_paragraph(stripped)
            i += 1

    def _add_heading(self, match):
        """添加标题（含自动编号）"""
        level = len(match.group(1))
        title = match.group(2).strip()

        if self.auto_numbering:
            # 真正的 Word 多级自动编号：
            # 标题段落只写入纯标题文本，编号由 numbering.xml 通过
            # Heading 样式自动渲染。H1 未绑定 numPr 不显示编号；
            # H2~H6 由样式触发自动编号（如"第1章"、"1.1"、"1.1.1"等）。
            full_title = title
        else:
            # 兼容模式：在标题文本前硬编码拼接编号字符串
            # 此时增删章节不会自动更新编号，需手动修改
            number = self.heading_numberer.get_number(level)
            if number:
                full_title = f"{number} {title}"
            else:
                full_title = title

        # 添加标题段落
        paragraph = self.doc.add_heading(full_title, level=level)

        # 应用标题样式（字体、字号、对齐）
        size_key = HEADING_FONT_SIZE.get(level, '小四号')
        font_size = FONT_SIZE_MAP.get(size_key, 12)
        align_str = HEADING_ALIGNMENT.get(level, 'left')

        if align_str == 'center':
            paragraph.alignment = self.WD_ALIGN_PARAGRAPH.CENTER
        else:
            paragraph.alignment = self.WD_ALIGN_PARAGRAPH.LEFT

        # 设置段前段后
        paragraph.paragraph_format.space_before = self.Pt(6)
        paragraph.paragraph_format.space_after = self.Pt(6)

        # 设置字体为黑体（颜色统一黑色，覆盖样式层蓝色主题色；斜体置 false，覆盖 Heading 4 样式层斜体）
        for run in paragraph.runs:
            self._set_run_font(run, font_name=DEFAULT_HEADING_FONT,
                               size=font_size, bold=True, italic=False,
                               color=BODY_COLOR)

    def _add_paragraph(self, text: str):
        """添加正文段落"""
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = self.WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph_format = paragraph.paragraph_format
        paragraph_format.first_line_indent = self.Cm(FIRST_LINE_INDENT_CM)
        paragraph_format.line_spacing = LINE_SPACING

        # 处理行内格式
        self._add_formatted_text(paragraph, text)

    def _add_formatted_text(self, paragraph, text: str):
        """处理行内格式（加粗、斜体、删除线、行内代码）"""
        last_end = 0

        for match in INLINE_FORMAT_PATTERN.finditer(text):
            # 添加前面的普通文本
            if match.start() > last_end:
                run = paragraph.add_run(text[last_end:match.start()])
                self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                   size=FONT_SIZE_MAP['小四号'])

            # 添加格式化文本
            if match.group(2):  # **加粗**
                run = paragraph.add_run(match.group(2))
                self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                   size=FONT_SIZE_MAP['小四号'], bold=True)
            elif match.group(3):  # *斜体*
                run = paragraph.add_run(match.group(3))
                self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                   size=FONT_SIZE_MAP['小四号'], italic=True)
            elif match.group(4):  # ~~删除线~~
                run = paragraph.add_run(match.group(4))
                self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                   size=FONT_SIZE_MAP['小四号'], strike=True)
            elif match.group(5):  # `行内代码`
                run = paragraph.add_run(match.group(5))
                self._set_run_font(run, font_name=DEFAULT_CODE_FONT,
                                   size=FONT_SIZE_MAP['五号'])

            last_end = match.end()

        # 添加剩余文本
        if last_end < len(text):
            run = paragraph.add_run(text[last_end:])
            self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                               size=FONT_SIZE_MAP['小四号'])

    def _add_image(self, match):
        """添加图片"""
        alt_text = match.group(1)
        img_path = match.group(2)

        # 解析图片完整路径
        if not os.path.isabs(img_path):
            # 优先从 images_dir 解析
            basename = os.path.basename(img_path)
            candidate = os.path.join(self.images_dir, basename)
            if os.path.exists(candidate):
                img_path = candidate
            else:
                # 尝试相对当前工作目录解析
                if not os.path.exists(img_path):
                    img_path = candidate  # 使用 images_dir 下的路径

        paragraph = self.doc.add_paragraph()
        paragraph.alignment = self.WD_ALIGN_PARAGRAPH.CENTER

        if os.path.exists(img_path):
            try:
                # 智能缩放：基于页面可用宽度和图片原始比例计算尺寸
                target_w, target_h = self._compute_image_size(img_path)
                run = paragraph.add_run()
                if target_h > 0:
                    run.add_picture(img_path, width=self.Cm(target_w),
                                    height=self.Cm(target_h))
                else:
                    # 无法读取尺寸，仅指定宽度（Word 自动按比例缩放高度）
                    run.add_picture(img_path, width=self.Cm(target_w))
            except Exception as e:
                # 图片插入失败，添加占位文字
                run = paragraph.add_run(f"[图片插入失败: {alt_text} - {str(e)}]")
                self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                   size=FONT_SIZE_MAP['小四号'])
        else:
            # 图片不存在，添加占位文字
            run = paragraph.add_run(f"[图片缺失: {alt_text}]")
            self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                               size=FONT_SIZE_MAP['小四号'])

    def _add_caption(self, match):
        """添加图题/表题"""
        caption_type = match.group(1)  # 图 或 表
        number = match.group(2)
        title = match.group(3)

        text = f"{caption_type} {number} {title}"
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = self.WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = self.Pt(3)
        paragraph.paragraph_format.space_after = self.Pt(6)

        run = paragraph.add_run(text)
        self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                           size=FONT_SIZE_MAP['五号'])

    def _add_table_title(self, match):
        """添加表格标题（粗体行）"""
        caption_type = match.group(1)
        number = match.group(2)
        title = match.group(3)

        text = f"{caption_type} {number} {title}"
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = self.WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = self.Pt(6)
        paragraph.paragraph_format.space_after = self.Pt(3)

        run = paragraph.add_run(text)
        self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                           size=FONT_SIZE_MAP['五号'], bold=True)

    def _add_table(self, lines: List[str], start_idx: int) -> int:
        """
        添加表格

        Args:
            lines: 所有行列表
            start_idx: 表格起始行索引

        Returns:
            int: 表格结束后的下一行索引
        """
        # 收集表格行
        table_lines = []
        i = start_idx
        while i < len(lines) and lines[i].strip().startswith('|'):
            table_lines.append(lines[i].strip())
            i += 1

        if len(table_lines) < 2:
            return start_idx + 1

        # 解析表格行
        rows = []
        for line in table_lines:
            # 跳过分隔行
            if TABLE_SEPARATOR_PATTERN.match(line):
                continue
            # 提取单元格内容
            cells = [c.strip() for c in line.strip('|').split('|')]
            rows.append(cells)

        if not rows:
            return i

        # 创建 Word 表格
        num_rows = len(rows)
        num_cols = max(len(row) for row in rows)
        table = self.doc.add_table(rows=num_rows, cols=num_cols)
        table.style = 'Table Grid'
        table.alignment = self.WD_TABLE_ALIGNMENT.CENTER

        # 填充表格内容
        for row_idx, row_data in enumerate(rows):
            for col_idx, cell_text in enumerate(row_data):
                if col_idx >= num_cols:
                    break
                cell = table.rows[row_idx].cells[col_idx]
                # 清空默认内容
                cell.text = ''
                paragraph = cell.paragraphs[0]
                paragraph.alignment = self.WD_ALIGN_PARAGRAPH.CENTER

                # 处理行内格式
                self._add_formatted_text(paragraph, cell_text)

                # 设置字体
                for run in paragraph.runs:
                    if row_idx == 0:
                        # 表头行：加粗、居中、灰底
                        self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                           size=FONT_SIZE_MAP['五号'], bold=True)
                    else:
                        # 数据行：宋体五号
                        self._set_run_font(run, font_name=DEFAULT_BODY_FONT,
                                           size=FONT_SIZE_MAP['五号'])

                # 表头行设置灰底
                if row_idx == 0:
                    self._set_cell_shading(cell, TABLE_HEADER_FILL)

        # 表格后空一行
        self.doc.add_paragraph()
        return i

    # 代码块样式常量（不花哨，仅以灰度区分命令块/终端输出块）
    _CODE_BLOCK_FILL = 'F5F5F5'        # 命令块底纹：浅灰
    _CODE_BLOCK_BORDER = 'CCCCCC'      # 命令块边框：浅灰
    _TERMINAL_BLOCK_FILL = 'E8E8E8'    # 终端输出块底纹：稍深灰
    _TERMINAL_BLOCK_BORDER = 'B8B8B8'  # 终端输出块边框：稍深灰

    # 终端输出块的语言标识集合（用于区分命令块和终端输出块）
    _TERMINAL_LANGS = {'text', 'console', 'output', 'log', 'plaintext',
                       'terminal', 'txt'}

    def _add_code_block(self, lines: List[str], start_idx: int) -> int:
        """
        添加代码块（带灰底和边框，区分命令块和终端输出块）。

        样式策略（保持低调，仅以灰度区分）：
        - 命令块（```bash/sh/shell/python 等）：浅灰底 #F5F5F5 + 浅灰边框 #CCCCCC
        - 终端输出块（```text/console/output/log 等）：稍深灰底 #E8E8E8 + 稍深灰边框 #B8B8B8

        Args:
            lines: 所有行列表
            start_idx: 代码块起始行索引（``` 开头的行）

        Returns:
            int: 代码块结束后的下一行索引
        """
        # 解析代码块语言标识（```bash、```text 等）
        start_line = lines[start_idx].strip()
        lang = ''
        if start_line.startswith('```'):
            lang = start_line[3:].strip().lower()

        i = start_idx + 1
        code_lines = []
        while i < len(lines) and not lines[i].strip().startswith('```'):
            code_lines.append(lines[i])
            i += 1

        # 跳过结束的 ```
        if i < len(lines):
            i += 1

        # 添加代码块段落
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = self.WD_ALIGN_PARAGRAPH.LEFT
        paragraph_format = paragraph.paragraph_format
        paragraph_format.left_indent = self.Cm(1)
        paragraph_format.space_before = self.Pt(6)
        paragraph_format.space_after = self.Pt(6)
        paragraph_format.line_spacing = 1.0  # 单倍行距，紧凑显示

        # 根据语言标识区分命令块和终端输出块
        is_terminal = lang in self._TERMINAL_LANGS
        if is_terminal:
            # 终端输出块：稍深的灰色底纹，与命令块形成视觉区分
            self._set_paragraph_border(paragraph,
                                        self._TERMINAL_BLOCK_BORDER)
            self._set_paragraph_shading(paragraph,
                                         self._TERMINAL_BLOCK_FILL)
        else:
            # 命令块/代码块：浅灰色底纹
            self._set_paragraph_border(paragraph, self._CODE_BLOCK_BORDER)
            self._set_paragraph_shading(paragraph, self._CODE_BLOCK_FILL)

        # 添加代码内容
        code_text = '\n'.join(code_lines)
        run = paragraph.add_run(code_text)
        self._set_run_font(run, font_name=DEFAULT_CODE_FONT,
                           size=FONT_SIZE_MAP['五号'])

        # 代码块后空一行
        self.doc.add_paragraph()
        return i

    def _add_quote(self, text: str):
        """添加引用"""
        paragraph = self.doc.add_paragraph()
        paragraph.paragraph_format.left_indent = self.Cm(1)
        paragraph.paragraph_format.space_before = self.Pt(3)
        paragraph.paragraph_format.space_after = self.Pt(3)

        # 处理行内格式
        self._add_formatted_text(paragraph, text)

        # 引用文本设置为斜体
        for run in paragraph.runs:
            run.italic = True

    def _add_list_item(self, text: str, ordered: bool = False,
                        number: Optional[str] = None):
        """
        添加列表项。

        直接使用文本编号（不使用 Word 的 List Number/List Bullet 样式），
        避免 Word 自动编号导致两类问题：
        1. 编号重复：Markdown 文本已含 "1. xxx"，List Number 样式会再
           自动加一层编号，出现 "1. 1. xxx"（视觉上类似 "1.1.xxx"）。
        2. 跨章节连号：Word 默认所有 List Number 段落共用同一 numId，
           编号会跨章节连续递增（如第一章 1~4，第二章 5~8）。

        实现方式：使用普通段落 + 文本编号 + 悬挂缩进（多行文本对齐）。
        """
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = self.WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph_format = paragraph.paragraph_format
        paragraph_format.line_spacing = LINE_SPACING
        # 悬挂缩进：左缩进 0.74cm，首行反向缩进 0.74cm
        # 使编号/符号在左，多行文本对齐到编号右侧
        paragraph_format.left_indent = self.Cm(FIRST_LINE_INDENT_CM)
        paragraph_format.first_line_indent = self.Cm(-FIRST_LINE_INDENT_CM)

        # 添加前缀（编号或符号）作为单独 run，便于独立设置字体
        if ordered and number:
            prefix = f"{number}. "
        else:
            prefix = '• '
        prefix_run = paragraph.add_run(prefix)
        self._set_run_font(prefix_run, font_name=DEFAULT_BODY_FONT,
                           size=FONT_SIZE_MAP['小四号'])

        # 处理剩余文本的行内格式（加粗、斜体、行内代码等）
        self._add_formatted_text(paragraph, text)

    def save(self, output_path: str):
        """保存 Word 文档"""
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        self.doc.save(output_path)


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='BidGenie Flow - Markdown 转 Word 脚本（阶段八）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python md_to_docx.py \\
      --input merged_proposal.md \\
      --output 2026-08-02_XX项目_技术方案.docx \\
      --project-name "XX项目" \\
      --images-dir images/

说明：
  - 将 Markdown 文件转换为 Word 文档
  - 应用样式模板（标题自动编号、正文宋体小四1.5倍行距、表格表头加粗灰底）
  - 图片居中、宽度 15cm
        """
    )
    parser.add_argument('--input', required=True, help='输入 Markdown 文件路径')
    parser.add_argument('--output', required=True, help='输出 Word 文件路径')
    parser.add_argument('--project-name', required=True, help='项目名称')
    parser.add_argument('--images-dir', default=None,
                        help='图片目录路径（默认为 input 同级 images/ 目录）')
    parser.add_argument('--auto-numbering', dest='auto_numbering',
                        action='store_true', default=True,
                        help='启用 Word 真正的多级自动编号（默认）')
    parser.add_argument('--no-auto-numbering', dest='auto_numbering',
                        action='store_false',
                        help='禁用自动编号，使用硬编码编号字符串（兼容旧行为）')

    args = parser.parse_args()

    # 读取输入文件
    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # 解析图片目录
    images_dir = args.images_dir or os.path.join(os.path.dirname(os.path.abspath(args.input)), 'images')

    # 创建转换器并转换
    try:
        converter = MdToDocxConverter(images_dir, args.project_name,
                                       auto_numbering=args.auto_numbering)
        converter.convert(md_content)
        converter.save(args.output)
        mode_desc = '多级自动编号' if (args.auto_numbering and converter.auto_numbering) else '硬编码编号'
        print(f"Word 文档已生成: {args.output}（编号模式: {mode_desc}）")
    except ImportError as e:
        print(f"依赖库错误: {str(e)}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"转换失败: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
