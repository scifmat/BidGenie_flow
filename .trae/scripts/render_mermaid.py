#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidGenie Flow - Mermaid 渲染脚本（阶段八）

功能：
1. 从 Markdown 文件中提取 Mermaid 代码块
2. 按 chart_mapping 映射表匹配 chart_id
3. 调用 mermaid-cli (mmdc) 渲染 PNG（支持三级降级）
4. 替换代码块为图片引用 + 标准图题格式
5. 输出处理后的 Markdown 到指定文件

命令行接口：
    python render_mermaid.py \
        --input <merged_proposal.md 路径> \
        --output <输出 Markdown 路径> \
        --images-dir <images 目录路径> \
        --chart-mapping <chart_id 到图题编号的 JSON 映射>

依赖库：
- mermaid-cli (Node.js 环境): npm install -g @mermaid-js/mermaid-cli
- Pillow: pip install Pillow

三级降级方案：
- 第一层：保留 Mermaid 代码块，记录异常
- 第二层：生成占位图（含标题和描述），替换原代码块
- 第三层：将图表转换为文字描述，插入正文对应位置
"""

import os
import sys
import re
import json
import argparse
import subprocess
import tempfile
import time
import shutil
from typing import Tuple, Optional, Dict, List


# ==========================================================
# 常量定义
# ==========================================================

# Mermaid 代码块正则匹配
# 匹配 ```mermaid ... ``` 形式的代码块
MERMAID_BLOCK_PATTERN = re.compile(
    r'```mermaid\s*\n(.*?)\n```',
    re.DOTALL
)

# 图题行匹配（如 *图 1-1-4-1 服务整体架构图*）
CHART_TITLE_PATTERN = re.compile(r'\*图\s+([\d-]+)\s+(.+?)\*')

# mermaid-cli 渲染超时（秒）
RENDER_TIMEOUT = 60

# 渲染失败重试次数
MAX_RETRY = 2

# 重试间隔（秒）
RETRY_INTERVAL = 30

# 图片宽度（像素）
IMAGE_WIDTH = 1200

# 占位图尺寸
PLACEHOLDER_WIDTH = 800
PLACEHOLDER_HEIGHT = 300


class MermaidRenderer:
    """Mermaid 渲染器，支持三级降级方案"""

    def __init__(self, images_dir: str, chart_mapping: Dict = None):
        """
        初始化渲染器

        Args:
            images_dir: 图片输出目录
            chart_mapping: chart_id 到图题信息的映射表
        """
        self.images_dir = os.path.abspath(images_dir)
        self.chart_mapping = chart_mapping or {}
        # 反向映射：figure_number → chart_id
        self._figure_to_chart_id = {}
        for chart_id, info in self.chart_mapping.items():
            fig_num = info.get('figure_number', '')
            if fig_num:
                self._figure_to_chart_id[fig_num] = chart_id

        # 确保图片目录存在
        os.makedirs(self.images_dir, exist_ok=True)

        # 渲染统计
        self.stats = {
            'total_charts': 0,
            'success_count': 0,
            'fallback_count': 0,
            'failed_count': 0,
            'chart_stats': [],
            'errors': []
        }

        # 检测 mermaid-cli 是否可用
        self.mmdc_available = self._check_mmdc_available()

    def _check_mmdc_available(self) -> bool:
        """检测 mermaid-cli (mmdc) 是否可用（Windows 兼容：使用 shutil.which 解析 .cmd 路径）"""
        mmdc_path = shutil.which('mmdc')
        if not mmdc_path:
            return False
        try:
            result = subprocess.run(
                [mmdc_path, '--version'],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            return False

    def _find_system_chrome(self) -> str:
        """
        查找系统已安装的 Chrome 或 Edge 浏览器路径。
        Windows 下 Puppeteer 下载的 Chromium 可能因缺依赖无法启动，
        优先使用系统已安装的 Chrome/Edge 解决此问题。

        Returns:
            str: 浏览器可执行文件路径，未找到返回空字符串
        """
        candidates = [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            os.path.expanduser(r'~\AppData\Local\Google\Chrome\Application\chrome.exe'),
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
            '/usr/bin/google-chrome',
            '/usr/bin/chromium-browser',
            '/usr/bin/chromium',
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return ''

    def _create_puppeteer_config(self) -> str:
        """
        创建 puppeteer 配置文件，指定使用系统 Chrome/Edge。
        如果找不到系统浏览器，返回空字符串（使用 mmdc 默认 Chromium）。

        Returns:
            str: 配置文件路径，未找到系统浏览器返回空字符串
        """
        chrome_path = self._find_system_chrome()
        if not chrome_path:
            return ''
        try:
            cfg = {
                'executablePath': chrome_path,
                'args': ['--no-sandbox', '--disable-dev-shm-usage']
            }
            cfg_path = os.path.join(self.images_dir, '_puppeteer_config.json')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f)
            return cfg_path
        except Exception:
            return ''

    def _find_chart_id_by_figure(self, figure_number: str) -> str:
        """根据图题编号反查 chart_id"""
        return self._figure_to_chart_id.get(figure_number, '')

    def _find_chart_id_by_order(self, node_id: str, order: int) -> str:
        """
        根据节点 ID 和图表顺序匹配 chart_id

        Args:
            node_id: 节点 ID（如 "1_1_4"）
            order: 该节点内图表序号（从 1 开始）

        Returns:
            str: chart_id，找不到返回空字符串
        """
        for chart_id, info in self.chart_mapping.items():
            if info.get('node_id') == node_id:
                # 简化匹配：取该节点下第 order 个图表
                # 实际通过遍历顺序保证
                pass
        # 简化实现：按 chart_id 命名规则构造（<node_id>_c<order>）
        candidate = f"{node_id}_c{order}"
        if candidate in self.chart_mapping:
            return candidate
        return candidate  # 即使不在映射中，也返回构造值

    def render_chart(self, chart_id: str, mermaid_code: str,
                     chart_info: Dict) -> Dict:
        """
        渲染单个 Mermaid 图表，支持三级降级

        Args:
            chart_id: 图表 ID（如 "1_1_4_c1"）
            mermaid_code: Mermaid 代码字符串
            chart_info: 图表信息（含 chart_title, chart_type, figure_number）

        Returns:
            dict: 渲染结果
                - success: 是否成功
                - png_path: PNG 文件路径（成功或占位图时返回）
                - fallback_level: 0=成功, 1=保留代码块, 2=占位图, 3=文字描述
                - error: 错误信息
                - markdown_replacement: 替换的 Markdown 内容
        """
        self.stats['total_charts'] += 1
        chart_title = chart_info.get('chart_title', chart_id)
        figure_number = chart_info.get('figure_number', '')
        chart_type = chart_info.get('chart_type', 'flowchart')

        # 标准 Markdown 替换内容（图片引用 + 图题）
        def _build_success_md(png_filename: str) -> str:
            return (
                f"![{chart_title}](images/{png_filename})\n\n"
                f"*图 {figure_number} {chart_title}*"
            )

        # 第三层降级：文字描述
        def _build_text_description_md() -> str:
            chart_desc = chart_info.get('chart_description', '')
            return (
                f"> **图 {figure_number} {chart_title}**\n"
                f">\n"
                f"> [图表描述] {chart_desc}\n"
                f">\n"
                f"> *注：该图表因渲染环境问题无法生成图片，已转换为文字描述*"
            )

        # 检查 mermaid-cli 是否可用
        if not self.mmdc_available:
            error_msg = "mermaid-cli (mmdc) 不可用，请先安装：npm install -g @mermaid-js/mermaid-cli"

            # 尝试第二层降级：生成占位图
            try:
                placeholder_path = self._generate_placeholder_image(
                    chart_id, chart_title, figure_number, chart_info
                )
                if placeholder_path:
                    png_filename = os.path.basename(placeholder_path)
                    self.stats['fallback_count'] += 1
                    self._record_stat(
                        chart_id, chart_title, chart_type, figure_number,
                        'fallback', 2, error_msg, '占位图替换'
                    )
                    return {
                        'success': False,
                        'png_path': placeholder_path,
                        'fallback_level': 2,
                        'error': error_msg,
                        'markdown_replacement': _build_success_md(png_filename)
                    }
            except Exception as e:
                error_msg = f"占位图生成失败: {str(e)}"

            # 第三层降级：文字描述
            self.stats['failed_count'] += 1
            self._record_stat(
                chart_id, chart_title, chart_type, figure_number,
                'failed', 3, error_msg, '文字描述替换'
            )
            return {
                'success': False,
                'png_path': None,
                'fallback_level': 3,
                'error': error_msg,
                'markdown_replacement': _build_text_description_md()
            }

        # 尝试渲染（最多重试 MAX_RETRY 次）
        png_filename = f"{chart_id}.png"
        png_path = os.path.join(self.images_dir, png_filename)
        last_error = ''

        for attempt in range(MAX_RETRY + 1):
            try:
                # 写入临时 .mmd 文件
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.mmd', delete=False, encoding='utf-8'
                ) as tmp_file:
                    tmp_file.write(mermaid_code)
                    tmp_mmd_path = tmp_file.name

                try:
                    # 调用 mmdc 渲染（Windows 兼容：使用 shutil.which 解析完整路径）
                    mmdc_path = shutil.which('mmdc') or 'mmdc'
                    cmd = [
                        mmdc_path,
                        '-i', tmp_mmd_path,
                        '-o', png_path,
                        '-w', str(IMAGE_WIDTH),
                        '-b', 'white',
                        '-t', 'default'
                    ]
                    # Windows 下 Puppeteer Chromium 可能无法启动，优先使用系统 Chrome/Edge
                    pptr_cfg_path = self._create_puppeteer_config()
                    if pptr_cfg_path:
                        cmd.extend(['-p', pptr_cfg_path])
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=RENDER_TIMEOUT
                    )

                    if result.returncode == 0 and os.path.exists(png_path):
                        # 渲染成功
                        self.stats['success_count'] += 1
                        self._record_stat(
                            chart_id, chart_title, chart_type, figure_number,
                            'success', 0, None, 'PNG 替换'
                        )
                        return {
                            'success': True,
                            'png_path': png_path,
                            'fallback_level': 0,
                            'error': None,
                            'markdown_replacement': _build_success_md(png_filename)
                        }
                    else:
                        last_error = result.stderr.strip() or result.stdout.strip() or '未知错误'
                finally:
                    # 清理临时文件
                    try:
                        os.unlink(tmp_mmd_path)
                    except OSError:
                        pass

            except subprocess.TimeoutExpired:
                last_error = f"渲染超时（第 {attempt + 1} 次，超时 {RENDER_TIMEOUT} 秒）"
            except FileNotFoundError:
                last_error = "mermaid-cli (mmdc) 未安装"
                break  # 不重试，直接降级
            except Exception as e:
                last_error = f"渲染异常: {str(e)}"

            # 等待后重试
            if attempt < MAX_RETRY:
                time.sleep(RETRY_INTERVAL)

        # 渲染失败，进入降级流程
        # 第二层降级：生成占位图
        try:
            placeholder_path = self._generate_placeholder_image(
                chart_id, chart_title, figure_number, chart_info
            )
            if placeholder_path:
                placeholder_filename = os.path.basename(placeholder_path)
                self.stats['fallback_count'] += 1
                self._record_stat(
                    chart_id, chart_title, chart_type, figure_number,
                    'fallback', 2, last_error, '占位图替换'
                )
                return {
                    'success': False,
                    'png_path': placeholder_path,
                    'fallback_level': 2,
                    'error': last_error,
                    'markdown_replacement': _build_success_md(placeholder_filename)
                }
        except Exception as e:
            last_error = f"占位图生成失败: {str(e)}"

        # 第三层降级：文字描述
        self.stats['failed_count'] += 1
        self._record_stat(
            chart_id, chart_title, chart_type, figure_number,
            'failed', 3, last_error, '文字描述替换'
        )
        return {
            'success': False,
            'png_path': None,
            'fallback_level': 3,
            'error': last_error,
            'markdown_replacement': _build_text_description_md()
        }

    def _generate_placeholder_image(self, chart_id: str, chart_title: str,
                                     figure_number: str, chart_info: Dict) -> Optional[str]:
        """
        生成占位图（第二层降级）

        增强特性：
        - 不截断 chart_description，显示完整描述
        - 自动按描述长度换行（每行约 40 字符）
        - 图片高度自适应描述行数

        Args:
            chart_id: 图表 ID
            chart_title: 图表标题
            figure_number: 图题编号
            chart_info: 完整图表信息

        Returns:
            str: 占位图文件路径，失败返回 None
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return None

        try:
            # 尝试加载中文字体
            font_large = None
            font_small = None
            for font_name in ['simsun.ttc', 'simhei.ttf', 'msyh.ttc', 'msyh.ttf']:
                try:
                    font_large = ImageFont.truetype(font_name, 24)
                    font_small = ImageFont.truetype(font_name, 16)
                    break
                except (OSError, IOError):
                    continue

            if font_large is None:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()

            # 文字内容
            title_text = f"图 {figure_number} {chart_title}"
            notice_text = "[图表渲染失败，请人工替换]"

            # 完整描述（不截断）
            chart_desc = chart_info.get('chart_description', '')
            desc_lines = [notice_text]
            if chart_desc:
                # 不截断，按约 40 字符自动换行
                desc_lines.append("描述:")
                # 手动换行（中文字符约 40 个/行）
                line_width = 40
                for i in range(0, len(chart_desc), line_width):
                    desc_lines.append(chart_desc[i:i + line_width])

            # 根据描述行数自适应图片高度
            line_height = 25
            title_block_height = 80
            desc_block_height = len(desc_lines) * line_height + 40
            image_height = max(PLACEHOLDER_HEIGHT, title_block_height + desc_block_height + 40)

            # 创建白色背景图片（高度自适应）
            image = Image.new('RGB', (PLACEHOLDER_WIDTH, image_height), color='white')
            draw = ImageDraw.Draw(image)

            # 绘制标题（居中）
            title_y = 30
            try:
                title_bbox = draw.textbbox((0, 0), title_text, font=font_large)
                title_width = title_bbox[2] - title_bbox[0]
                title_x = (PLACEHOLDER_WIDTH - title_width) // 2
            except Exception:
                title_x = PLACEHOLDER_WIDTH // 2 - 100
            draw.text((title_x, title_y), title_text, fill='black', font=font_large)

            # 绘制分隔线
            separator_y = title_y + 40
            draw.line([(50, separator_y), (PLACEHOLDER_WIDTH - 50, separator_y)],
                      fill='gray', width=1)

            # 绘制描述文字（多行，居中）
            desc_y = separator_y + 20
            for idx, line in enumerate(desc_lines):
                try:
                    desc_bbox = draw.textbbox((0, 0), line, font=font_small)
                    desc_width = desc_bbox[2] - desc_bbox[0]
                    desc_x = (PLACEHOLDER_WIDTH - desc_width) // 2
                except Exception:
                    desc_x = PLACEHOLDER_WIDTH // 2 - 100
                # 第一行（提示文字）用灰色，描述部分用深灰色
                fill_color = 'gray' if idx == 0 else 'darkgray'
                draw.text((desc_x, desc_y + idx * line_height), line,
                          fill=fill_color, font=font_small)

            # 保存占位图
            placeholder_filename = f"{chart_id}_placeholder.png"
            placeholder_path = os.path.join(self.images_dir, placeholder_filename)
            image.save(placeholder_path, 'PNG')

            return placeholder_path
        except Exception:
            return None

    def _record_stat(self, chart_id: str, chart_title: str, chart_type: str,
                      figure_number: str, render_result: str, fallback_level: int,
                      error: Optional[str], handling: str):
        """记录渲染统计"""
        self.stats['chart_stats'].append({
            'chart_id': chart_id,
            'title': chart_title,
            'type': chart_type,
            'figure_number': figure_number,
            'render_result': render_result,
            'fallback_level': fallback_level,
            'error': error,
            'handling': handling
        })

        if error:
            self.stats['errors'].append({
                'chart_id': chart_id,
                'chart_title': chart_title,
                'chart_type': chart_type,
                'figure_number': figure_number,
                'error': error,
                'fallback_level': fallback_level,
                'handling': handling
            })

    def process_markdown(self, md_content: str) -> Tuple[str, Dict]:
        """
        处理 Markdown 内容，提取并渲染所有 Mermaid 代码块

        Args:
            md_content: 原始 Markdown 内容

        Returns:
            tuple: (处理后的 Markdown 内容, 渲染统计)
        """
        # 查找所有 Mermaid 代码块
        # 使用 finditer 进行替换，避免重复匹配问题
        matches = list(MERMAID_BLOCK_PATTERN.finditer(md_content))

        if not matches:
            return md_content, self.stats

        # 倒序替换，避免位置偏移
        result_content = md_content
        for match in reversed(matches):
            mermaid_code = match.group(1).strip()
            block_start = match.start()
            block_end = match.end()

            # 查找紧随其后的图题行（跳过空行）
            after_block = result_content[block_end:]
            chart_id = ''
            chart_info = None

            # 尝试从图题行匹配 chart_id
            title_match = CHART_TITLE_PATTERN.match(after_block.lstrip())
            if title_match:
                figure_number = title_match.group(1)
                chart_title = title_match.group(2)
                chart_id = self._find_chart_id_by_figure(figure_number)
                if chart_id:
                    chart_info = self.chart_mapping.get(chart_id)

            # 如果通过图题未匹配到，尝试从代码块内容中提取 node_id
            if not chart_id:
                # 尝试从 Mermaid 代码的注释中提取 chart_id
                # 格式：%% chart_id: 1_1_4_c1
                cid_match = re.search(r'%%\s*chart_id:\s*([\w_]+)', mermaid_code)
                if cid_match:
                    chart_id = cid_match.group(1)
                    chart_info = self.chart_mapping.get(chart_id)

            # 如果仍未匹配，按出现顺序构造 chart_id
            if not chart_id:
                # 使用序号构造（不太准确，但作为兜底）
                chart_id = f"chart_{len(self.stats['chart_stats']) + 1}"
                chart_info = {
                    'chart_id': chart_id,
                    'chart_title': chart_title if title_match else chart_id,
                    'chart_type': 'flowchart',
                    'figure_number': title_match.group(1) if title_match else '',
                    'chart_description': ''
                }

            # 如果有 chart_info 但缺图题编号，构造一个
            if chart_info and not chart_info.get('figure_number'):
                # 从 chart_id 推断（去掉 _cN 后缀）
                base = re.sub(r'_c\d+$', '', chart_id)
                chart_info['figure_number'] = base.replace('_', '-')

            # 执行渲染
            render_result = self.render_chart(chart_id, mermaid_code, chart_info or {})

            # 替换原代码块为渲染结果
            replacement = render_result['markdown_replacement']

            # 包含图题行一起替换（如果存在）
            if title_match:
                # 找到图题行的结束位置
                title_line_end = len(after_block) - len(after_block.lstrip())
                title_line = after_block.lstrip().split('\n')[0]
                title_line_end += len(title_line)
                # 替换代码块 + 图题行
                result_content = (
                    result_content[:block_start] +
                    replacement +
                    result_content[block_end + title_line_end:]
                )
            else:
                # 仅替换代码块
                result_content = (
                    result_content[:block_start] +
                    replacement +
                    result_content[block_end:]
                )

        return result_content, self.stats


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='BidGenie Flow - Mermaid 渲染脚本（阶段八）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python render_mermaid.py \\
      --input merged_proposal.md \\
      --output merged_proposal_with_images.md \\
      --images-dir images/ \\
      --chart-mapping chart_mapping.json

说明：
  - 从 input 文件提取 Mermaid 代码块，渲染为 PNG，替换为图片引用
  - 输出到 output 文件，图片存入 images-dir 目录
  - chart-mapping 为 JSON 文件，含 chart_id 到图题信息的映射
        """
    )
    parser.add_argument('--input', required=True, help='输入 Markdown 文件路径')
    parser.add_argument('--output', required=True, help='输出 Markdown 文件路径')
    parser.add_argument('--images-dir', required=True, help='图片输出目录路径')
    parser.add_argument('--chart-mapping', default=None,
                        help='chart_id 到图题信息的 JSON 映射文件路径')
    parser.add_argument('--chart-mapping-json', default=None,
                        help='chart_id 到图题信息的 JSON 字符串（直接传入）')
    parser.add_argument('--stats-output', default=None,
                        help='渲染统计 JSON 输出文件路径（推荐使用，规避 PowerShell stdout 重定向问题）')

    args = parser.parse_args()

    # 读取输入文件
    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # utf-8-sig：兼容带 BOM 的输入文件（PS 5.1 Out-File/Set-Content 产物），
    # 对无 BOM 文件同样兼容
    with open(args.input, 'r', encoding='utf-8-sig') as f:
        md_content = f.read()

    # 解析 chart_mapping
    chart_mapping = {}
    if args.chart_mapping:
        if os.path.exists(args.chart_mapping):
            # utf-8-sig：兼容带 BOM 的 JSON 文件（同上）
            with open(args.chart_mapping, 'r', encoding='utf-8-sig') as f:
                chart_mapping = json.load(f)
        else:
            print(f"警告: chart-mapping 文件不存在: {args.chart_mapping}", file=sys.stderr)
    elif args.chart_mapping_json:
        try:
            chart_mapping = json.loads(args.chart_mapping_json)
        except json.JSONDecodeError as e:
            print(f"警告: chart-mapping-json 解析失败: {str(e)}", file=sys.stderr)

    # 确保图片目录存在
    os.makedirs(args.images_dir, exist_ok=True)

    # 创建渲染器并处理
    renderer = MermaidRenderer(args.images_dir, chart_mapping)
    render_start = time.time()
    processed_content, stats = renderer.process_markdown(md_content)
    render_duration = time.time() - render_start
    # 耗时精度：< 1 秒显示毫秒，>= 1 秒显示秒
    if render_duration < 1:
        stats['duration'] = f'{int(render_duration * 1000)} 毫秒'
    else:
        stats['duration'] = f'{render_duration:.1f} 秒'

    # 写入输出文件
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(processed_content)

    # 输出统计信息（JSON 格式，便于主控 Agent 解析）
    stats_output = {
        'success': True,
        'result': stats,
        'output_file': args.output
    }
    stats_json = json.dumps(stats_output, ensure_ascii=False, indent=2)
    if args.stats_output:
        # 写入指定文件（推荐方式，规避 PowerShell stdout 重定向问题）
        with open(args.stats_output, 'w', encoding='utf-8') as f:
            f.write(stats_json)
        print(f"渲染统计已写入: {args.stats_output}")
    else:
        print(stats_json)

    # 清理 puppeteer 配置临时文件
    pptr_cfg = os.path.join(args.images_dir, '_puppeteer_config.json')
    if os.path.exists(pptr_cfg):
        try:
            os.remove(pptr_cfg)
        except OSError:
            pass


if __name__ == '__main__':
    main()
