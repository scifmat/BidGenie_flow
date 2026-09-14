---
alwaysApply: false
description: 需要使用'.trae/scripts/'和'.trae/utils/'文件夹下的辅助工具时
---
# 辅助工具说明

## 工具使用场景

| 工具 | 使用场景 | 调用方式 |
|------|----------|----------|
| run_skill.py | 当 Agent 无法直接导入 SKILL.py 时 | 命令行调用 |
| temp_manager.py | 文件转换、解析过程中的临时文件存储 | SKILL.py 内部调用 |

## 工具使用说明
### 1.run_skill.py — Skill 统一调用入口

**文件位置**：`.trae/scripts/run_skill.py`

**作用**：解决 `.agents` 目录无法直接作为 Python 包导入的问题，提供统一的命令行接口调用各 Skill 函数。

**使用方法**：
```bash
python .trae/scripts/run_skill.py <skill_name> <function_name> [参数]
```

**支持的参数**：
| 参数 | 简写 | 说明 |
|------|------|------|
| --workspace_path | -w | 工作空间路径 |
| --files | -f | 文件路径列表（可多个） |
| --package | -p | 标段编号 |
| --word_count | -c | 预期总字数 |
| --status | -s | 项目状态 |
| --rename_map | -r | 重命名字典（JSON 字符串） |
| --fields | -d | 字段字典（JSON 字符串） |
| --requirements | -req | 招标文件要求字典（JSON 字符串） |
| --timestamp | -t | 时间戳 |

**调用示例**：
```bash
# 文件转换
python .trae/scripts/run_skill.py file_conversion convert_documents --files "招标文件.docx"

# 创建目录结构
python .trae/scripts/run_skill.py document_parsing create_extraction_structure --workspace_path bid_project/test

# 生成补充信息模板
python .trae/scripts/run_skill.py information_supplement generate_supplementary_template --workspace_path bid_project/test
```

**返回格式**：JSON 格式
```json
{"success": true, "result": {...}}
{"success": false, "error": "错误信息", "skill": "...", "function": "..."}
```

### 2.temp_manager.py — 临时文件管理工具

**文件位置**：`.trae/utils/temp_manager.py`

**作用**：在系统临时目录下创建项目专属临时文件夹，用于存放转换过程中的中间文件，避免工作空间污染。

**使用方法**：
```python
# 在 SKILL.py 中直接调用便捷函数
from .trae.utils.temp_manager import create_temp_dir, save_temp_file, cleanup_expired_temp

# 创建临时目录
temp_dir = create_temp_dir(project_id='HBZB-2026-123456')

# 保存临时文件
file_path = save_temp_file('HBZB-2026-123456', 'temp_data.txt', 'Hello, World!')

# 清理过期临时文件（保留7天）
cleanup_expired_temp(days=7)
```

**注意**：由于 `.trae` 目录有前缀点号，直接使用相对导入会失败。各 SKILL.py 已内置集成了 TempManager 的便捷函数，Agent 可以直接调用 SKILL.py 中暴露的函数。

