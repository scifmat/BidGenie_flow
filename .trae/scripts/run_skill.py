#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidGenie Flow - Skill Runner
统一入口脚本，解决 .agents 目录无法直接作为 Python 包导入的问题。

文件位置：.trae/scripts/run_skill.py
项目根目录：BidGenie_flow/（自动检测）

用法：
python .trae/scripts/run_skill.py <skill_name> <function_name> --workspace_path <path> [--arg1 <value> ...]

示例：
python .trae/scripts/run_skill.py file_conversion convert_documents --files "招标文件.docx"
python .trae/scripts/run_skill.py information_supplement generate_supplementary_template --workspace_path bid_project/xxx

说明：
- 本脚本自动检测项目根目录（包含 .agents 和 .trae 子目录的目录）
- 通过 importlib.util 动态加载 SKILL.py，绕过 .agents 目录的相对导入限制
- 返回结果为 JSON 格式，便于 Agent 解析

JSON 参数传递说明（重要）：
================================================================
针对 --rename_map、--fields、--requirements 等 JSON 字符串参数，
不同终端环境下的正确调用方式如下：

【PowerShell 5.1】（Windows 默认，重要！）
  PS 5.1 向原生命令传参时会剥离参数内部的双引号，例如：
    --rename_map '{"key":"value"}'  实际到达 Python 时变成 {key:value}
  本脚本内置"引号剥离修复器"可自动修复这种损坏（支持中文键名、
  数字/点号开头的文件名键、数组元素等），因此单引号写法可直接使用。
  但当 JSON 字符串值内部含有逗号、冒号、花括号等字符时，修复可能
  失效，此时推荐使用文件方式：
    1) 使用 Write 工具（或编辑器）创建 JSON 文件（无 BOM）
    2) python .trae/scripts/run_skill.py ... --rename_map_file data.json
  _file 模式已兼容带 BOM 的文件（PS 5.1 Out-File/Set-File -Encoding UTF8
  产生的 BOM 不再导致解析失败）。

  备选：使用反引号转义双引号（PS 5.1 原生可靠）
    python .trae/scripts/run_skill.py ... --rename_map "{\`"key\`":\`"value\`"}"

【PowerShell 7+】
  单引号包裹即可原生支持：
    python .trae/scripts/run_skill.py ... --rename_map '{"key":"value"}'

【CMD】（推荐使用双引号包裹+内部双引号转义）
  python .trae/scripts/run_skill.py ... --rename_map "{\"key\":\"value\"}"

【Bash/Linux/macOS】（推荐使用单引号包裹）
  python .trae/scripts/run_skill.py ... --rename_map '{"key":"value"}'

为避免终端环境差异导致的问题，本脚本支持以下容错机制：
1. 自动去除参数值外围的单/双引号
2. 支持 _file 后缀参数（从文件读取 JSON 内容，兼容 BOM）
3. 支持宽松 JSON 解析（自动修复常见的引号转义问题）
4. PS 5.1 引号剥离修复：自动为被剥离引号的键/值/数组元素补回引号
5. 参数拆散重组：PS 5.1 将含空格的 JSON 拆成多个参数时自动拼回
================================================================
"""

import os
import sys
import json
import re
import argparse
import importlib.util
import tempfile
import platform
import subprocess


def find_project_root():
    """
    自动检测项目根目录（包含 .agents 和 .trae 子目录的目录）

    Returns:
        str: 项目根目录路径
    """
    # 从当前脚本位置向上查找
    current_dir = os.path.abspath(os.path.dirname(__file__))
    # 当前位置：.trae/scripts/，向上返回 2 级到项目根目录
    # .trae/scripts/ -> .trae/ -> 项目根目录
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))

    # 验证是否找到正确的项目根目录
    if os.path.exists(os.path.join(project_root, '.agents')) and os.path.exists(os.path.join(project_root, '.trae')):
        return project_root

    # 如果没找到，尝试其他方式
    for _ in range(5):
        project_root = os.path.abspath(os.path.join(project_root, '..'))
        if os.path.exists(os.path.join(project_root, '.agents')) and os.path.exists(os.path.join(project_root, '.trae')):
            return project_root

    # 默认使用当前目录的父目录
    return os.path.abspath(os.path.join(current_dir, '..', '..'))


# 全局项目根目录
PROJECT_ROOT = find_project_root()


def load_skill_module(skill_name):
    """
    加载指定的 Skill 模块

    Args:
        skill_name: Skill 名称（如 file_conversion、document_parsing、information_supplement）

    Returns:
        module: 加载的模块对象
    """
    skill_path = os.path.join(
        PROJECT_ROOT,
        '.agents', 'skills', skill_name, 'SKILL.py'
    )

    if not os.path.exists(skill_path):
        raise FileNotFoundError(f"Skill 模块不存在: {skill_path}")

    # 使用 importlib.util 动态加载模块
    spec = importlib.util.spec_from_file_location(f"skill_{skill_name}", skill_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def call_skill_function(skill_name, function_name, **kwargs):
    """
    调用 Skill 的指定函数

    Args:
        skill_name: Skill 名称
        function_name: 函数名称
        **kwargs: 函数参数

    Returns:
        dict: 函数返回结果（JSON 序列化）
    """
    try:
        module = load_skill_module(skill_name)

        if not hasattr(module, function_name):
            raise AttributeError(f"函数 {function_name} 不存在于 {skill_name} Skill 中")

        func = getattr(module, function_name)
        result = func(**kwargs)

        return {
            'success': True,
            'result': result
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'skill': skill_name,
            'function': function_name
        }


# 全局缓存：避免重复的环境检测
_ENV_CACHE = None

def detect_shell_environment():
    """
    检测当前运行环境（PowerShell、CMD、Bash 等）

    Returns:
        str: 'powershell' | 'cmd' | 'bash' | 'unknown'
    """
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE

    env = 'unknown'
    try:
        if platform.system() == 'Windows':
            # 通过 COMSPEC 环境变量判断
            comspec = os.environ.get('COMSPEC', '').lower()
            if 'cmd' in comspec:
                # 检查是否在 PowerShell 中运行
                parent_proc = os.environ.get('PSModulePath', '')
                if parent_proc:
                    env = 'powershell'
                else:
                    # 尝试通过 PowerShell 命令探测
                    try:
                        result = subprocess.run(
                            ['powershell', '-Command', '$PSVersionTable.PSVersion'],
                            capture_output=True, text=True, timeout=2
                        )
                        if result.returncode == 0:
                            env = 'powershell'
                        else:
                            env = 'cmd'
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        env = 'cmd'
            else:
                env = 'windows'
        else:
            # Unix/Linux/macOS
            env = 'bash'
    except Exception:
        env = 'unknown'

    _ENV_CACHE = env
    return env


# JSON 标量（数字/true/false/null）在补引号时应保持原样
_JSON_SCALAR_RE = re.compile(r'^-?\d+(\.\d+)?([eE][+-]?\d+)?$|^(true|false|null)$', re.IGNORECASE)

# 未加引号的键名：出现在 { 或 , 之后、冒号之前（键名内部允许空格，用于
# 重组后的修复；不含引号/结构符）
_UNQUOTED_KEY_RE = re.compile(r'([{,]\s*)([^"\s:{}\[\],][^:{}\[\],]*?)\s*:')

# 未加引号的值：冒号后到 , } ] 或字符串末尾之间的内容（允许内部空格）
_UNQUOTED_VALUE_RE = re.compile(r'(:\s*)([^"\s,{}\[\]][^,{}\[\]]*?)(\s*(?=[,}\]]|$))')

# 未加引号的数组元素：[ 或 , 之后到 , ] 或末尾之间的内容（排除对象/嵌套）
_UNQUOTED_ELEM_RE = re.compile(r'([\[,]\s*)([^"\s,{}\[\]:][^,{}\[\]:]*?)(\s*(?=[,\]]|$))')


def _quote_value(text):
    """值为 JSON 标量（数字/true/false/null）时保持原样，否则补双引号"""
    if _JSON_SCALAR_RE.match(text):
        return text
    return '"%s"' % text.strip()


def repair_unquoted_json(value):
    """
    修复 PowerShell 5.1 剥离双引号后损坏的 JSON，返回解析后的对象。

    背景：PS 5.1 向原生命令传参时不会转义参数内部的双引号，导致
        --fields '{"项目编号": "TEST-01"}'
    到达 Python 时变成：
        {项目编号: TEST-01}
    （全部双引号被剥离，字符串内部含空格时参数还会被拆散——后者由
    main() 中的 parse_known_args 重组机制处理）

    修复规则：
        1. 为未加引号的键名补回双引号（支持中文、数字、点号、含空格键名）
        2. 为未加引号的字符串值补回双引号（数字/true/false/null 保持原样）
        3. 为未加引号的数组元素补回双引号（同上标量豁免）

    局限：值内部本身包含逗号/花括号等结构符时无法无损恢复（原始信息已
    丢失），此时应使用 _file 后缀参数传 JSON。

    Args:
        value: 被剥离引号的 JSON 字符串

    Returns:
        dict/list: 修复并解析后的 JSON 对象

    Raises:
        json.JSONDecodeError: 修复后仍不是合法 JSON 时抛出
    """
    repaired = value

    # 规则1：键名补引号
    repaired = _UNQUOTED_KEY_RE.sub(
        lambda m: '%s"%s":' % (m.group(1), m.group(2)), repaired
    )

    # 规则2：值补引号（非标量）
    repaired = _UNQUOTED_VALUE_RE.sub(
        lambda m: '%s%s' % (m.group(1), _quote_value(m.group(2))), repaired
    )

    # 规则3：数组元素补引号（非标量）
    repaired = _UNQUOTED_ELEM_RE.sub(
        lambda m: '%s%s' % (m.group(1), _quote_value(m.group(2))), repaired
    )

    # 修复后必须可解析，返回解析结果（与其他解析器保持一致的返回类型）
    return json.loads(repaired)


def parse_json_arg(value, arg_name='', auto_fallback=True):
    """
    容错地解析 JSON 字符串参数（增强版，支持 PowerShell 友好模式）

    针对不同终端环境下的引号处理差异，提供多层容错：
    1. 去除外围单/双引号
    2. 标准 json.loads 解析
    3. 处理 PowerShell 特有转义（反斜杠+双引号、反引号转义）
    4. 处理单引号包裹的 JSON
    5. 处理键名未加引号的情况
    6. 尝试从临时文件回退（auto_fallback=True 时）

    Args:
        value: 原始参数值
        arg_name: 参数名称（用于错误提示）
        auto_fallback: 解析失败时是否自动回退到临时文件（仅 PowerShell 环境）

    Returns:
        dict/list: 解析后的 JSON 对象

    Raises:
        ValueError: 解析失败时抛出，包含详细的错误信息和修复建议
    """
    if not value:
        return {}

    # 去除参数值外围的引号
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == "'" and cleaned[-1] == "'":
        cleaned = cleaned[1:-1]
    if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"':
        cleaned = cleaned[1:-1]

    # 尝试链：逐级尝试修复
    attempts = [
        ('标准解析', lambda v: json.loads(v)),
        ('反斜杠转义', lambda v: json.loads(v.replace('\\"', '"'))),
        ('反引号+反斜杠转义', lambda v: json.loads(v.replace('\\`"', '"').replace('\\"', '"'))),
        ('PowerShell 反引号转义', lambda v: json.loads(v.replace('`"', '"'))),
        ('单引号修复', lambda v: json.loads(re.sub(r"(?<!\\)'", '"', v))),
        ('键名补全', lambda v: json.loads(re.sub(r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', v))),
        # PS 5.1 引号剥离修复：键/值/数组元素全面补引号（支持中文键名、
        # 数字点号开头的文件名键等，数字/true/false/null 保持标量原样）
        ('PS5.1 引号剥离修复', repair_unquoted_json),
    ]

    for attempt_name, parser in attempts:
        try:
            return parser(cleaned)
        except (json.JSONDecodeError, NameError):
            continue

    # 如果 auto_fallback 为 True 且在 PowerShell 环境，尝试临时文件回退
    shell_env = detect_shell_environment()
    if auto_fallback and shell_env in ('powershell', 'cmd'):
        # 尝试直接从原始值生成临时 JSON 文件
        try:
            temp_path = write_temp_json(value, arg_name)
            if temp_path:
                result = read_json_from_file(temp_path, arg_name)
                # 清理临时文件
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                return result
        except (ValueError, FileNotFoundError, Exception):
            pass

    # 所有尝试均失败
    error_hint = get_fallback_hint(value, arg_name, shell_env)
    raise ValueError(error_hint)


def write_temp_json(value, arg_name):
    """
    将 JSON 参数写入临时文件用于回退解析

    Args:
        value: 原始参数值
        arg_name: 参数名称

    Returns:
        str: 临时文件路径，写入失败返回 None
    """
    try:
        # 清理值并尝试多种方式组合
        candidates = []

        # 清理引号
        cleaned = value.strip()
        if len(cleaned) >= 2:
            if cleaned[0] == "'" and cleaned[-1] == "'":
                candidates.append(cleaned[1:-1])
            if cleaned[0] == '"' and cleaned[-1] == '"':
                candidates.append(cleaned[1:-1])
        candidates.append(cleaned)

        # 尝试各种转义修复组合
        for c in candidates:
            try:
                parsed = json.loads(c)
            except json.JSONDecodeError:
                try:
                    parsed = json.loads(c.replace('\\"', '"'))
                except json.JSONDecodeError:
                    try:
                        parsed = json.loads(c.replace('`"', '"').replace('\\"', '"'))
                    except json.JSONDecodeError:
                        continue
                else:
                    pass
            else:
                # 找到可解析的值，写入临时文件
                temp_dir = tempfile.gettempdir()
                temp_name = f'bidgenie_json_{arg_name}_{os.getpid()}.json'
                temp_path = os.path.join(temp_dir, temp_name)
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(parsed, f, ensure_ascii=False)
                return temp_path
    except Exception:
        pass
    return None


def get_fallback_hint(value, arg_name, shell_env):
    """
    生成友好的错误提示和修复建议

    Args:
        value: 原始参数值
        arg_name: 参数名称
        shell_env: 当前环境

    Returns:
        str: 错误提示文本
    """
    # 提取并简化原始值用于显示
    display_val = value.strip()[:200]
    if len(value.strip()) > 200:
        display_val += '...'

    hints = [
        f"JSON 参数解析失败（参数名: {arg_name}）",
        f"原始值: {display_val!r}",
        "",
    ]

    if shell_env == 'powershell':
        hints.extend([
            "=== PowerShell 推荐方案 ===",
            "",
            "方案1（复杂 JSON 最可靠）：使用 --{0}_file 参数".format(arg_name),
            "  # Step 1: 创建 JSON 文件（Write 工具或下述命令均可，已兼容 BOM）",
            '  @\'',
            '  {',
            '    "key1": "value1",',
            '    "key2": "value2"',
            '  }',
            '  \'@ | Out-File -FilePath temp_json.json -Encoding utf8',
            "",
            "  # Step 2: 使用文件参数",
            f'  python .trae/scripts/run_skill.py ... --{arg_name}_file temp_json.json',
            "",
            "方案2（简单 JSON 可用，已内置 PS5.1 引号剥离修复）：",
            f'  python .trae/scripts/run_skill.py ... --{arg_name} \'{{"key":"value"}}\'',
            "  注意：JSON 值内部含逗号/冒号/花括号时修复可能失效，请用方案1",
            "",
            "方案3（反引号转义双引号，PS 5.1 原生可靠）：",
            f'  python .trae/scripts/run_skill.py ... --{arg_name} "{{\\`"key\\`":\\`"value\\`\"}}"',
        ])
    elif shell_env == 'cmd':
        hints.extend([
            "=== CMD 推荐方案 ===",
            "",
            "方案1（最可靠）：使用 --{0}_file 参数".format(arg_name),
            "  创建 JSON 文件后使用 --{0}_file 参数",
            "",
            "方案2（转义双引号）：",
            f'  python .trae/scripts/run_skill.py ... --{arg_name} "{{\\"key\\":\\"value\\"}}"',
        ])
    elif shell_env == 'bash':
        hints.extend([
            "=== Bash 推荐方案 ===",
            "",
            "方案1（单引号包裹）：",
            f'  python .trae/scripts/run_skill.py ... --{arg_name} \'{{"key":"value"}}\'',
            "",
            "方案2（使用 --{0}_file 参数）：".format(arg_name),
            "  python .trae/scripts/run_skill.py ... --{0}_file data.json".format(arg_name),
        ])
    else:
        hints.extend([
            "=== 通用方案 ===",
            "",
            "方案1：使用 --{0}_file 参数（推荐）".format(arg_name),
            "",
            "方案2：根据您的终端环境选择正确的引号转义方式",
        ])

    return "\n".join(hints)


def read_json_from_file(file_path, arg_name=''):
    """
    从文件读取 JSON 内容

    Args:
        file_path: JSON 文件路径
        arg_name: 原始参数名称（用于错误提示）

    Returns:
        dict/list: 解析后的 JSON 对象
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"JSON 文件不存在（参数 --{arg_name}_file）: {file_path}"
        )
    try:
        # utf-8-sig：兼容带 BOM 的文件（PS 5.1 Out-File/Set-Content -Encoding UTF8
        # 会写入 BOM，纯 utf-8 读取会报 "Unexpected UTF-8 BOM"）；对无 BOM 文件同样兼容
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSON 文件内容解析失败（参数 --{arg_name}_file）: {file_path}\n"
            f"错误: {str(e)}"
        )


def main():
    # 检测环境
    shell_env = detect_shell_environment()

    # 构建帮助文档中的环境感知提示
    env_hint = ""
    if shell_env == 'powershell':
        env_hint = "\n\n**检测到 PowerShell 环境**：建议使用 --xxx_file 参数从文件读取 JSON，或使用单引号包裹 JSON 字符串。"

    parser = argparse.ArgumentParser(
        description='BidGenie Flow Skill Runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
============================================================
环境感知提示：当前运行在 {env} 环境
============================================================

JSON 参数传递说明（针对不同终端环境）：

【PowerShell 环境】（当前环境）
  ⭐ 推荐方案1：使用单引号包裹 JSON（PS 5.1 已内置引号剥离修复）
    python .trae/scripts/run_skill.py file_conversion rename_files ^
        --workspace_path bid_project/xxx ^
        --rename_map '{{"01_source.md":"01_Bidding_Documents.md"}}'
    （JSON 值内部含逗号/冒号/花括号等复杂字符时，请改用方案2）

  ⭐ 推荐方案2：使用 _file 后缀参数（复杂 JSON 最可靠）
    python .trae/scripts/run_skill.py file_conversion rename_files ^
        --workspace_path bid_project/xxx ^
        --rename_map_file rename_map.json
    （_file 模式兼容 BOM；可用 Write 工具或 @'...'@ | Out-File 创建）

  备选方案3：使用反引号转义双引号（PS 5.1 原生可靠）
    python .trae/scripts/run_skill.py ... --rename_map "{{\`"01_source.md\`":\`"01_Bidding_Documents.md\`"}}"

【CMD 环境】
  python .trae/scripts/run_skill.py ... --rename_map "{{{{\\"key\\":\\"value\\"}}}}"

【Bash/Linux/macOS 环境】
  python .trae/scripts/run_skill.py ... --rename_map '{{"key":"value"}}'

============================================================
PowerShell 友好模式（--ps-mode）：
  启用后，脚本会自动尝试更多的转义解析策略，
  并在解析失败时自动尝试回退到临时文件方案。
============================================================
{env_hint}
        """.format(env=shell_env.upper(), env_hint=env_hint),
        add_help=True
    )

    # 位置参数
    parser.add_argument('skill_name', help='Skill 名称')
    parser.add_argument('function_name', help='要调用的函数名称')

    # 通用参数
    parser.add_argument('--workspace_path', '-w', help='工作空间路径')
    parser.add_argument('--files', '-f', nargs='+', help='文件路径列表')
    parser.add_argument('--package', '-p', help='标段编号')
    parser.add_argument('--word_count', '-c', help='预期总字数')
    parser.add_argument('--status', '-s', help='项目状态')
    parser.add_argument('--timestamp', '-t', help='时间戳')
    parser.add_argument('--package_count', '-k', type=int, default=None, help='标段数量')
    parser.add_argument('--node_id', '-n', help='节点 ID')
    parser.add_argument('--increment', '-i', type=int, default=None, help='重试计数增量')
    parser.add_argument('--task_type', help='审查任务类型')
    parser.add_argument('--round', type=int, default=None, help='优化轮次（1、2、3）')
    parser.add_argument('--user_feedback', help='用户反馈内容（自然语言）')

    # JSON 字符串参数
    parser.add_argument('--rename_map', '-r',
                        help='重命名字典（JSON 字符串）',
                        metavar='JSON_STR')
    parser.add_argument('--rename_map_file',
                        help='重命名字典 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--fields', '-d',
                        help='字段字典（JSON 字符串）',
                        metavar='JSON_STR')
    parser.add_argument('--fields_file',
                        help='字段字典 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--requirements', '-req',
                        help='招标文件要求字典（JSON 字符串）',
                        metavar='JSON_STR')
    parser.add_argument('--requirements_file',
                        help='招标文件要求字典 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--issues',
                        help='审查问题列表（JSON 字符串，阶段七 group_issues_by_node 使用）',
                        metavar='JSON_STR')
    parser.add_argument('--issues_file',
                        help='审查问题列表 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--target_node_ids',
                        help='目标节点 ID 列表（JSON 字符串，阶段七 run_revalidation 使用）',
                        metavar='JSON_STR')
    parser.add_argument('--target_node_ids_file',
                        help='目标节点 ID 列表 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--optimization_records',
                        help='优化执行记录列表（JSON 字符串，阶段七 generate_optimization_report 使用）',
                        metavar='JSON_STR')
    parser.add_argument('--optimization_records_file',
                        help='优化执行记录列表 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--export_stats',
                        help='导出统计信息（JSON 字符串，阶段八 generate_merge_report 使用）',
                        metavar='JSON_STR')
    parser.add_argument('--export_stats_file',
                        help='导出统计信息 JSON 文件路径（PowerShell 推荐）',
                        metavar='FILE_PATH')
    parser.add_argument('--export_file_path',
                        help='导出文件路径（阶段八 update_metadata_status 使用，可选）')

    # PowerShell 友好模式
    parser.add_argument('--ps-mode',
                        action='store_true',
                        default=(shell_env == 'powershell'),
                        help='PowerShell 友好模式（自动启用更多转义策略，PowerShell 环境下默认开启）')
    parser.add_argument('--no-ps-mode',
                        action='store_true',
                        default=False,
                        help='禁用 PowerShell 友好模式')
    parser.add_argument('--debug-json',
                        action='store_true',
                        default=False,
                        help='启用 JSON 参数调试模式，输出详细解析过程')

    args, unknown_args = parser.parse_known_args()

    # PS 5.1 参数拆散重组：当 JSON 字符串值内部含空格时，PS 5.1 会把
    # 一个参数拆成多个（如 '{"key one": "value two"}' 拆为
    # ['{key', 'one: value', 'two}']）。argparse 会把多余片段归入
    # unknown。此处将其按原顺序用空格拼回，追加到 JSON 参数值后重试解析。
    if unknown_args:
        reassembled = ' '.join(unknown_args)
        if args.debug_json:
            print(f"[DEBUG] 检测到被 PS 5.1 拆散的参数片段: {unknown_args!r}")
        # 依次尝试把片段拼到各 JSON 字符串参数值后面，取第一个可解析成功的
        for json_attr in ('rename_map', 'fields', 'requirements', 'issues',
                          'target_node_ids', 'optimization_records', 'export_stats'):
            base_value = getattr(args, json_attr, None)
            if not base_value:
                continue
            try:
                merged = base_value + ' ' + reassembled
                parse_json_arg(merged, json_attr, auto_fallback=False)
                # 拼接后可解析 → 采纳拼接结果
                setattr(args, json_attr, merged)
                if args.debug_json:
                    print(f"[DEBUG] 参数片段已重组到 --{json_attr}: {merged!r}")
                break
            except (ValueError, Exception):
                continue

    # 确定是否启用 PowerShell 模式
    ps_mode = args.ps_mode and not args.no_ps_mode
    auto_fallback = ps_mode  # PowerShell 模式下自动启用临时文件回退

    if args.debug_json:
        print(f"[DEBUG] Shell 环境: {shell_env}")
        print(f"[DEBUG] PowerShell 模式: {ps_mode}")
        print(f"[DEBUG] 自动回退: {auto_fallback}")

    # 构建函数参数
    kwargs = {}
    if args.workspace_path:
        kwargs['workspace_path'] = args.workspace_path
    if args.files:
        kwargs['files'] = args.files
    if args.package:
        kwargs['package'] = args.package
    if args.word_count:
        kwargs['word_count'] = args.word_count
    if args.status:
        kwargs['status'] = args.status
    if args.timestamp:
        kwargs['timestamp'] = args.timestamp
    if args.package_count is not None:
        kwargs['package_count'] = args.package_count
    if args.node_id:
        kwargs['node_id'] = args.node_id
    if args.increment is not None:
        kwargs['increment'] = args.increment
    if args.task_type:
        kwargs['task_type'] = args.task_type
    if args.round is not None:
        kwargs['round'] = args.round
    if args.user_feedback:
        kwargs['user_feedback'] = args.user_feedback
    if args.export_file_path:
        kwargs['export_file_path'] = args.export_file_path

    # JSON 参数处理：优先使用 _file 参数，其次使用 JSON 字符串参数
    # 在 PowerShell 模式下，_file 参数优先度更高
    json_params_config = [
        ('rename_map', 'rename_map_file', args.rename_map, args.rename_map_file),
        ('fields', 'fields_file', args.fields, args.fields_file),
        ('requirements', 'requirements_file', args.requirements, args.requirements_file),
        ('issues', 'issues_file', args.issues, args.issues_file),
        ('target_node_ids', 'target_node_ids_file', args.target_node_ids, args.target_node_ids_file),
        ('optimization_records', 'optimization_records_file', args.optimization_records, args.optimization_records_file),
        ('export_stats', 'export_stats_file', args.export_stats, args.export_stats_file),
    ]

    json_errors = []
    for arg_name, file_arg_name, str_value, file_value in json_params_config:
        try:
            if file_value:
                # 使用 _file 参数从文件读取
                if args.debug_json:
                    print(f"[DEBUG] {arg_name}: 使用文件模式 -> {file_value}")
                kwargs[arg_name] = read_json_from_file(file_value, arg_name)
            elif str_value:
                # 使用 JSON 字符串参数（启用 PowerShell 友好模式）
                if args.debug_json:
                    print(f"[DEBUG] {arg_name}: 使用字符串模式 -> {str_value!r}")
                kwargs[arg_name] = parse_json_arg(
                    str_value, arg_name, auto_fallback=auto_fallback
                )
            else:
                # 两种方式都没有，跳过
                pass
        except (ValueError, FileNotFoundError) as e:
            json_errors.append(str(e))

    if json_errors:
        # JSON 解析失败，输出结构化错误信息
        error_result = {
            'success': False,
            'error': "; ".join(json_errors),
            'error_type': 'json_parse_error',
            'skill': args.skill_name,
            'function': args.function_name,
            'shell_environment': shell_env,
            'ps_mode': ps_mode,
            'recommendations': get_json_recommendations(shell_env)
        }
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)

    # 调用函数并输出结果
    result = call_skill_function(args.skill_name, args.function_name, **kwargs)
    print(json.dumps(result, ensure_ascii=False))


def get_json_recommendations(shell_env):
    """
    根据当前环境返回 JSON 参数传递建议

    Args:
        shell_env: 检测到的 shell 环境

    Returns:
        list: 建议列表
    """
    if shell_env == 'powershell':
        return [
            "简单 JSON 可直接用单引号包裹（已内置 PS 5.1 引号剥离自动修复）",
            "复杂 JSON（值含逗号/冒号/花括号）推荐使用 _file 后缀从文件读取（已兼容 BOM）",
            "反引号转义双引号在 PS 5.1 下原生可靠：--param \"{\\`\"key\\`\":\\`\"value\\`\"}\"",
            "示例：python .trae/scripts/run_skill.py ... --rename_map_file data.json",
        ]
    elif shell_env == 'cmd':
        return [
            "在 CMD 中传递 JSON 参数时，使用 _file 后缀从文件读取最可靠",
            "使用转义双引号：--param \"{\\\"key\\\":\\\"value\\\"}\"",
        ]
    elif shell_env == 'bash':
        return [
            "在 Bash 中传递 JSON 参数时，使用单引号包裹",
            "示例：--param '{\"key\":\"value\"}'",
        ]
    return [
        "推荐使用 _file 后缀从文件读取 JSON 参数，避免 shell 转义问题",
    ]


if __name__ == '__main__':
    main()
