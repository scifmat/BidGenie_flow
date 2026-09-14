#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionStart Hook 处理脚本
功能：在会话开始时注入项目规范和操作指导

健壮性设计（Windows/PowerShell 兼容）：
1. 详细执行日志：写入 .trae/hooks_logs/session_start.log（时间戳、PID、cwd、
   argv、stdin 原文、环境快照、输出长度、退出码），用于验证 hook 是否被
   Trae 真实触发以及诊断调用上下文；日志超 2MB 自动轮转
2. stdin 以字节读取后按 UTF-8 解码（errors='replace'），不依赖
   PYTHONIOENCODING/PYTHONUTF8 环境变量
3. stdout 强制重配置为 UTF-8，保证中文上下文在任意机器上无损输出
4. 任何异常（空 stdin、非法 JSON、内部错误）都不中断 hook：始终输出合法
   JSON 并以退出码 0 结束（SessionStart 注入类 hook 失败无恢复价值，
   不应阻塞会话启动）
"""

import json
import os
import sys
import traceback
from datetime import datetime

# ---------------------------------------------------------------------------
# 日志基础设施（所有异常静默吞掉，绝不影响 hook 主流程）
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TRAE_DIR = os.path.dirname(_SCRIPT_DIR)
LOG_DIR = os.path.join(_TRAE_DIR, 'hooks_logs')
LOG_FILE = os.path.join(LOG_DIR, 'session_start.log')
LOG_MAX_BYTES = 2 * 1024 * 1024  # 2MB 触发轮转


def _rotate_log_if_needed():
    """日志超过 2MB 时轮转为 .old，防止无限增长"""
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
            old = LOG_FILE + '.old'
            if os.path.exists(old):
                os.remove(old)
            os.replace(LOG_FILE, old)
    except Exception:
        pass


def log(message):
    """追加一行日志（带毫秒级时间戳），任何异常都不抛出"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _rotate_log_if_needed()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {message}\n')
    except Exception:
        pass


def read_stdin_raw():
    """以字节方式读取 stdin，再按 UTF-8 容错解码（规避控制台编码差异）"""
    raw = b''
    try:
        raw = sys.stdin.buffer.read()
    except Exception as e:
        log(f'stdin 读取异常: {type(e).__name__}: {e}')
    try:
        return raw.decode('utf-8', errors='replace'), raw
    except Exception:
        return '', raw


def build_additional_context():
    """构造注入给会话的项目规范上下文（业务内容）"""
    return """【BidGenie Flow 项目规范】
1. 本项目是投标文件技术方案自动化撰写工作流
2. 工作流程：文件上传 -> 文件分析 -> 信息补充 -> 大纲编写 -> 正文撰写 -> 内容审查 -> 内容优化 -> 合并导出
3. 关键文件：metadata.json、outline.json、Supplementary_info.md
4. 工作空间目录：bid_project/下的动态命名目录
5. 禁止删除以下目录：source_file、extraction_file、proposal_file、review_file、final_document_file

【阶段一：文件上传 操作规范】
1. 调用 convert_documents(files) 转换文件
2. 读取转换后的 01_source.md、02_source.md 等文件内容
3. 根据内容识别文件类型，确定最终文件名
4. 调用 rename_files(workspace_path, rename_map) 执行重命名
5. 验证重命名结果，确保所有文件已正确命名
6. 从招标文件中提取关键信息（项目编号、项目名称、采购方式、是否分标段、项目标段数）
7. 调用 update_metadata_fields(workspace_path, fields) 回填到 metadata.json
[注意] 只有完成关键信息回填，阶段一才算真正完成！

【阶段二：文件分析 操作规范】
1. 确定工作空间，读取 metadata.json 确认项目状态为"文件上传完成"
2. 自行判断标段情况，决策子智能体调度策略
3. 调用 create_extraction_structure 创建目录结构
4. 启动 extract-info-agent 子智能体提取信息（主控自行决定数量和方式）
5. 子智能体完成后，直接阅读提取文件校验内容完整性
6. 调用 update_metadata_from_extraction 校验元数据一致性（不覆盖阶段一已回填的字段）
7. 调用 update_metadata_status 更新项目状态为"文件分析完成"
[注意] 校验由主控 Agent 通过阅读文件自行完成，不依赖脚本自动判断！

【阶段三：信息补充 操作规范】
1. 读取 metadata.json 确认项目状态为"文件分析完成"，读取"采购方式"判断项目类型
2. 第一步——确认关键参数：
   a) 分标段时用 AskUserQuestion 确认标段(仅一个)，调用 update_metadata_package 回填
   b) 用 AskUserQuestion 确认预期总字数，调用 update_metadata_wordcount 回填
3. 第二步——创建模板并等待用户填写：
   a) 调用 read_extraction_for_supplementary 读取提取文件，分析 7 类补充信息的招标文件要求
   b) Agent 使用 Write 工具直接创建 Supplementary_info.md（参考 bid_flow_docs/附件1-项目结构与配置说明.md 的 1.5 章节，适配项目类型：工程施工/服务采购/货物采购）
   c) 调用 AskUserQuestion 提示用户手动填写模板，指明文件位置、填写规范及注意事项
   d) 进入等待状态，直至用户完成填写并选择继续
4. 第三步——校验与完成：
   a) 用户填写完成后，调用 validate_supplementary_info 校验完整性
   b) 主控 Agent 直接阅读文件执行语义检查，必要时整理优化
   c) 确认内容无误后，调用 update_metadata_status 更新项目状态为"信息补充完成"
[注意] 阶段三无 Subagent,所有工作由主控 Agent 直接完成！
[注意] Supplementary_info.md 由 Agent 使用 Write 工具直接创建（非脚本生成），用户填写补充内容！

【阶段四：大纲编写 操作规范】
1. 读取 metadata.json 确认项目状态为"信息补充完成"，读取"预期总字数"、"采购方式"和"当前需撰写标段"
2. 调用 read_input_files(workspace_path, package) 校验输入文件存在性（package 从"当前需撰写标段"转换：标段2→2，01→1）
3. 主控 Agent 调用 outline-agent 子智能体执行大纲编写：
   a) outline-agent 确认 metadata.json 中「当前需撰写标段」字段的值，确定需要读取的提取文件
   b) outline-agent 解析对应标段的技术评分标准（packages_{N}/07_Evaluation_Criteria.md）
   c) outline-agent 读取对应标段的其它已提取的技术文档（packages_{N}/06_Procurement_Content.md、packages_{N}/09_Technical_Requirements.md）
   d) outline-agent 根据评审因素构建树形大纲结构，结合技术评分标准和其它技术相关文档规划细纲和字数分配
   e) outline-agent 判断图表生成需求，设置 generate_chart 和 charts 字段
   f) outline-agent 使用 Write 工具直接创建 outline.json（保存到 proposal_file/ 目录）
4. 主控 Agent 调用 validate_outline_structure(workspace_path) 校验大纲结构完整性
5. 调用 generate_outline_md(workspace_path) 生成 outline.md 供用户审查
6. 主控 Agent 使用 AskUserQuestion 提交大纲供用户确认：
   a) 用户确认：继续步骤7
   b) 用户不确认：outline-agent 根据用户反馈修改大纲（反复，直到用户确认为止）
7. 用户确认后，调用 generate_directory_structure(workspace_path) 生成 proposal_file 目录结构
8. 调用 update_metadata_status 更新项目状态为"大纲确认完成"
[注意] SKILL.md 指导主控 Agent 如何协调工作，outline-agent.md 指导 subagent 如何执行具体编写！
[注意] 大纲的解析、构建、字数分配、图表判断等智能工作由 outline-agent 完成，SKILL.py 仅负责文件操作和校验！
[注意] outline.json 由 outline-agent 使用 Write 工具直接创建（非脚本生成），outline.md 由 SKILL.py 生成！

【阶段五：正文撰写 操作规范】
1. 读取 metadata.json 确认项目状态为"大纲确认完成"，读取"预期总字数"、"采购方式"和"当前需撰写标段"
2. 调用 read_outline_and_materials(workspace_path) 读取大纲和撰写素材：
   a) 仅读取对技术方案撰写有用的文件：01_Basic_Information.md、06_Procurement_Content.md、07_Evaluation_Criteria.md、08_Business_Requirements.md、09_Technical_Requirements.md、Supplementary_info.md、metadata.json、outline.json
   b) 不读取资质商务方面的文件：02_Eligibility_Review.md、03_Invalid_Bid_Item.md、04_Compilation_Requirements.md、05_Substantive_Response.md（避免上下文爆炸）
3. 调用 build_task_queue(workspace_path) 构建撰写任务队列：
   a) 从 outline.json 中提取所有 write_content=true 的节点
   b) 检查节点是否存在 depends_on 字段：
      i) 存在 depends_on：根据该字段构建节点依赖图，使用拓扑排序算法生成执行顺序（自动检测循环依赖并回退到 DFS）
      ii) 不存在 depends_on：默认按大纲深度优先遍历顺序执行（同级节点可并行）
   c) 自动过滤无效依赖关系（被依赖节点不存在于大纲中）
   d) 标记同级无依赖节点为可并行执行
   e) 【检查点恢复】自动识别失败节点并优先重试：
      - build_task_queue 内部会调用 identify_failed_nodes 自动扫描文件状态
      - 文件不存在或字数严重不足（<50%）的节点会被自动加入 failed_nodes
      - failed_nodes 中的节点会被优先排在任务队列最前（标记为 retry 状态）
      - 重试次数超过 MAX_RETRY_COUNT（默认 2 次）的节点标记为 exhausted，需人工介入
4. 主控 Agent 按队列顺序调度 writer-agent 执行撰写任务（优先执行 retry 任务）：
   a) 最多同时启动 3 个 writer-agent（资源限制）
   b) 有依赖关系的节点按依赖顺序串行执行
   c) 无依赖的同级节点可并行执行
   d) writer-agent 收到任务后，自行读取素材、撰写正文、生成 Mermaid 图表、写入 .md 文件
   e) 每个节点完成后调用 update_completed_nodes(workspace_path, node_id) 更新检查点
   f) 【失败处理】writer-agent 执行失败时调用 update_completed_nodes(node_id, 'failed') 标记失败
   g) 【重试计数】重试失败后调用 update_retry_count(workspace_path, node_id) 增加重试计数
5. 每个 writer-agent 完成后，调用 word_count_statistics(workspace_path) 更新字数统计
   [注意] 字数控制策略：只下限不限上限（字数不足 -15% 为不合格，超标仅记录不限制）
6. 所有任务完成后，调用 quality_self_check(workspace_path) 执行质量自查：
   a) 标题层级检查
   b) 格式规范检查
   c) 内容完整性检查（关键词覆盖率 < 50% 判定为问题；50%-80% 建议主控 Agent 进行语义检查兜底）
   d) 图表规范检查
7. 调用 generate_summary_report(workspace_path) 生成撰写完成报告
8. 调用 update_metadata_status 更新项目状态为"正文撰写完成"
[注意] SKILL.md 指导主控 Agent 如何协调工作，writer-agent.md 指导 subagent 如何执行具体撰写！
[注意] 正文撰写、图表生成等智能工作由 writer-agent 完成，SKILL.py 仅负责文件操作、任务队列管理和质量检查！
[注意] writer-agent 必须严格遵循 .trae/rules/writing_rules.md 中的撰写规则！
[注意] 采用串/并行混合调度策略，最多同时启动 3 个 writer-agent，避免资源过度消耗！
[注意] 使用检查点机制记录已完成节点，支持中断恢复！
[注意] outline-agent 已在阶段四生成 depends_on 字段，build_task_queue 会据此执行拓扑排序实现任务并行化！
[注意] 正文撰写阶段仅读取对技术方案有用的文件（01、06、07、08、09），避免资质商务内容导致上下文爆炸！
[注意] 【检查点恢复机制】build_task_queue 自动识别失败节点（文件缺失/字数严重不足），优先重试，超过 MAX_RETRY_COUNT 标记为 exhausted！

【阶段六：内容审查 操作规范】
1. 读取 metadata.json 确认项目状态为"正文撰写完成"，读取"当前需撰写标段"和"预期总字数"
2. 调用 read_review_materials(workspace_path) 读取审查素材：
   a) proposal_file/outline.json（大纲结构）
   b) proposal_file/*.md（所有正文文件）
   c) proposal_file/summary_report.md（阶段五撰写报告）
   d) extraction_file/packages_file/package_N/07_Evaluation_Criteria.md（评审标准）
   e) extraction_file/packages_file/package_N/09_Technical_Requirements.md（技术要求）
   f) metadata.json（项目元数据）
3. 调用 script_review(workspace_path) 执行脚本审查（机械性检查）：
   a) 字数符合度审查：统计各章节实际字数，与 word_count 对比（只下限不限上限：实际字数少于计划字数偏差 > 15% 为一般问题，实际字数超过计划字数仅记录不限制）
   b) 图表正确性审查：检查 Mermaid 语法、图表数量匹配、图题格式规范
   c) 章节结构审查：检查标题层级、标题格式、层级超限、段落格式
4. 调用 plan_ai_review_tasks(workspace_path) 智能规划 AI 审查任务（脚本→语义双轨制核心）：
   a) 基于脚本审查结果决定哪些 AI 审查任务需要执行、优先级如何
   b) 字数严重不足（<50%）→ 强制内容完整性审查（high 优先级）
   c) 实际字数极少（<50字）→ 强制内容完整性审查（high 优先级）
   d) 图表数量不匹配 → 强制评分点响应审查（high 优先级）
   e) 标题层级问题 → 强制技术与语言规范审查（medium 优先级）
   f) 无结构问题 → 技术与语言规范审查标记为可选（low 优先级，可仅做抽样检查）
5. 调用 get_ai_review_status(workspace_path) 检测 AI 审查任务完成情况（中断恢复）：
   a) 已完成（completed）的任务跳过
   b) pending 状态的任务调度 reviewer-agent 执行
   c) failed 状态的任务调度 reviewer-agent 重试
6. 主控 Agent 按 plan_ai_review_tasks 推荐顺序调度 reviewer-agent 执行 AI 审查：
   a) 任务1：内容完整性审查（content_completeness）→ 输出到 review_file/ai_review_content.json
   b) 任务2：评分点响应审查（scoring_response）→ 输出到 review_file/ai_review_scoring.json
   c) 任务3：技术与语言规范审查（technical_language）→ 输出到 review_file/ai_review_language.json
   d) 最多同时启动 3 个 reviewer-agent（资源限制），三个任务可并行执行
   e) reviewer-agent 完成后将结果写入 review_file/ai_review_*.json（必须包含 review_results 字段）
   f) 【失败处理】reviewer-agent 失败时调用 update_ai_review_retry_count(workspace_path, task_type) 增加重试计数
7. 调用 identify_failed_ai_reviews(workspace_path) 识别失败的 AI 审查任务：
   a) 失败且可重试的任务 → 重新调度 reviewer-agent
   b) 重试次数超过 AI_REVIEW_MAX_RETRY（默认 2 次）的任务 → 记录为 exhausted，需人工介入
8. 调用 collect_review_results(workspace_path) 收集所有审查结果（脚本审查+AI审查）
9. 调用 classify_and_prioritize(workspace_path) 执行问题分级和优先级排序：
   a) 严重问题：缺失要点≥2个、未响应评分点≥1个、逻辑漏洞（必须优化）
   b) 一般问题：缺失要点=1个、响应不充分、内容重复>20%、实际字数少于计划字数偏差>15%（建议优化，与阶段五一致，只下限不限上限）
   c) 建议性问题：轻微遗漏、语言风格不一致（视情况优化）
10. 调用 generate_optimization_report(workspace_path) 生成优化建议报告：
    a) 审查概览（总问题数、各级别问题数）
    b) 审查维度汇总
    c) 问题分级列表（按优先级排序）
    d) 审查通过判定和处理建议
11. 调用 update_metadata_status 更新项目状态为"内容审查完成"
[注意] SKILL.md 指导主控 Agent 如何协调工作，reviewer-agent.md 指导 subagent 如何执行具体审查！
[注意] 【脚本+语义双轨制】能使用脚本的就用脚本（字数、图表、章节结构），用脚本效果不好的就使用语义检查（内容完整性、评分点响应、技术语言规范）！
[注意] reviewer-agent 必须严格遵循 .trae/rules/review_rules.md 中的审查规则！
[注意] reviewer-agent 必须将结果写入 review_file/ai_review_*.json，主控 Agent 通过 get_ai_review_status 自动检测完成情况！
[注意] 【AI 审查自动化】plan_ai_review_tasks 基于脚本审查结果智能规划 AI 审查任务，避免无效 Agent 调用！
[注意] 【AI 审查重试机制】失败任务自动重试，超过 AI_REVIEW_MAX_RETRY 标记为 exhausted 需人工介入！
[注意] 问题分级机制：严重问题≥1必须优化，一般问题建议优化，仅建议性问题视情况优化；阶段六仅作审查，审查完成后统一进入阶段七优化！
[注意] 脚本审查先于AI审查执行，脚本审查结果可为AI审查提供参考！

【阶段七：内容优化 操作规范】
1. 读取 metadata.json 确认项目状态为"内容审查完成"，读取"当前需撰写标段"、"预期总字数"
2. 调用 update_optimization_round(workspace_path, round=1) 初始化优化轮次（第一轮）
3. 调用 read_optimization_inputs(workspace_path) 读取优化输入：
   a) optimization_suggestions.md（阶段六审查报告，主输入）
   b) ai_review_content.json / ai_review_scoring.json / ai_review_language.json（AI 审查结果）
   c) proposal_file/outline.json（大纲结构）
   d) proposal_file/*.md（所有正文文件）
   e) extraction_file/packages_file/package_N/07_Evaluation_Criteria.md（评审标准）
   f) extraction_file/packages_file/package_N/09_Technical_Requirements.md（技术要求）
   [注意] 本函数内部复用阶段六的 collect_review_results 收集审查问题列表，同时兼容 ai_review_*.json 的扩展 node_reviews 格式
   [注意] success=false 时向用户报告 missing_files，提示补充后重新执行
4. 调用 group_issues_by_node(issues, workspace_path) 按节点分组问题（避免写冲突）：
   a) batch_1_serious：含严重问题的节点（优先级最高，必须优化）
   b) batch_2_general：仅含一般问题的节点（建议优化）
   c) batch_3_suggestion：仅含建议性问题的节点（视情况优化）
   [注意] 无问题时直接跳到步骤7（生成空报告并提交用户审查）
   [注意] 同节点去重：相同问题描述合并为一个
5. 主控 Agent 调度 optimizer-agent 执行分级优化（按批次顺序：严重→一般→建议）：
   a) 最多同时启动 3 个 optimizer-agent（资源限制）
   b) 按 node_id 分组：同节点所有问题合并为一个任务（避免写冲突）
   c) 同批次内不同节点可并行执行（受 3 个并发上限约束）
   d) optimizer-agent 收到任务后，自行读取素材、分析问题、执行分级优化（严重→重写、一般→补充、建议→微调）、覆盖写入 .md 文件
   e) 单个节点失败不影响其他节点，失败节点记录到 metadata.json 的 optimization_failed_nodes
   f) 【重试机制】失败节点最多重试 2 次（OPTIMIZER_MAX_RETRY=2），调用 update_optimization_retry_count(workspace_path, node_id, increment=1) 管理计数
   g) 重试耗尽的节点标记为 exhausted，需人工介入
   h) 传递参数：workspace_path、node_id、node_title、content_plan、word_count、charts、issues、round、user_feedback（仅 round>1 时）
   [注意] optimizer-agent 必须严格遵循 .trae/rules/optimization_rules.md、writing_rules.md、anti_ai_writing_rules.md！
   [注意] optimizer-agent 不修改 outline.json、metadata.json、审查报告文件，仅覆盖写入原 .md 文件！
6. 调用 run_revalidation(workspace_path, round=1, target_node_ids=None) 执行二次验证（复用阶段六能力）：
   a) 脚本审查：调用阶段六的 script_review 函数（字数、图表、章节结构 3 维度）
   b) AI 审查：调用阶段六的 plan_ai_review_tasks 规划任务，主控 Agent 据此调度 reviewer-agent 执行
   c) reviewer-agent 完成后，主控 Agent 再次调用本函数或 collect_review_results 收集结果
   d) 验证结果判定：所有严重问题已修复→通过；仍存在严重问题→自动追加一轮优化（最多追加 1 次）
   [注意] target_node_ids 用于用户反馈循环时仅验证被修改的节点（减少开销）
7. 调用 generate_optimization_report(workspace_path, round=1, optimization_records=None) 生成优化报告：
   a) 报告路径：review_file/optimization_report.md（追加模式，每轮优化追加一个章节）
   b) 报告内容：优化概览、优化执行记录、二次验证结果（脚本+AI 审查）、当前问题清单
   c) optimization_records 由主控 Agent 提供（含 node_id、node_title、method、summary）
8. 调用 update_metadata_status(workspace_path, "自动优化完成") 更新项目状态：
   a) 同步更新 optimization_status 为 auto_completed
   b) 阶段 7A（自动优化）结束

【阶段 7B：人工审查 + 优化循环】
9. 主控 Agent 通过 AskUserQuestion 向用户提交人工审查请求：
   a) 展示 optimization_report.md 路径和优化概览摘要
   b) 展示未修复问题清单（如有）
   c) 询问用户：确认通过 / 提出修改意见
10. 【用户确认通过】
   a) 调用 lock_proposal_files(workspace_path) 锁定所有正文 .md 文件
      - 在 metadata.json 添加 proposal_files_locked: true 和 lock_time 字段
      - 锁定后 optimizer-agent 和后续阶段应拒绝修改正文
   b) 调用 update_metadata_status(workspace_path, "审查优化全部完成") 更新状态
   c) 通知用户：所有正文已锁定，可进入阶段八（合并导出）
11. 【用户提出修改意见】（优化循环，最多 3 次）
   a) 收集用户修改意见（自然语言），整理为结构化需求列表
   b) 调用 check_outline_structure_change(user_feedback, workspace_path) 检查是否涉及大纲结构变更：
      - 涉及变更（新增/删除/移动章节、修改标题等）→ 先调用 outline-agent 更新 outline.json，重新生成 outline.md 和目录结构
      - 不涉及变更 → 直接整理为优化任务
   c) 调用 group_user_feedback(user_feedback, workspace_path) 将用户反馈按节点分组
   d) 调用 update_optimization_round(workspace_path, round=2) 更新优化轮次
   e) 调度 optimizer-agent 执行第二轮优化（round=2），仅处理用户反馈涉及的问题
   f) 调用 run_revalidation(workspace_path, round=2, target_node_ids=[被修改节点]) 二次验证（仅验证被修改节点）
   g) 调用 generate_optimization_report(workspace_path, round=2) 追加第二轮优化记录
   h) 回到步骤9 重新提交用户审查
   [注意] 优化循环最多 3 次（含首轮自动优化共 3 轮），超出后暂停流程，请求人工介入

【阶段七中断恢复机制】
- 调用 get_optimization_status(workspace_path) 获取优化状态：
  a) optimization_status: pending/in_progress/auto_completed/user_reviewing/completed
  b) optimization_round: 当前优化轮次（0=未开始, 1-3=各轮次）
  c) optimization_completed_nodes: 已优化的节点列表
  d) optimization_failed_nodes: 优化失败的节点列表
  e) optimization_retry_counts: 重试计数 {node_id: count}
  f) proposal_files_locked: 正文文件是否锁定
- 调用 check_failed_optimizations(workspace_path) 识别失败优化任务：
  a) failed_nodes: 失败节点列表（含 retry_count、can_retry）
  b) retryable_nodes: 可重试节点列表
  c) exhausted_nodes: 重试耗尽节点列表（需人工介入）
- 中断恢复策略：
  a) optimization_status=pending → 从步骤1重新开始
  b) optimization_status=in_progress → 从中断处继续（检查已完成节点，仅执行未完成节点）
  c) optimization_status=auto_completed → 从步骤9（用户审查）继续
  d) optimization_status=user_reviewing → 重新提交用户审查
[注意] SKILL.md 指导主控 Agent 如何协调工作，optimizer-agent.md 指导 subagent 如何执行具体优化！
[注意] 内容重写、图表修正等智能工作由 optimizer-agent 完成，SKILL.py 仅负责文件操作、问题分组、状态管理和二次验证调度！
[注意] 二次验证复用阶段六的 script_review 和 reviewer-agent，不重新实现审查逻辑！
[注意] 最多同时启动 3 个 optimizer-agent，避免资源过度消耗！
[注意] 用户审查循环最多 3 次（含首轮自动优化），超出后暂停流程！
[注意] 用户通过人工审查后必须锁定正文文件，通过 metadata.json 的 proposal_files_locked 字段标记！
[注意] 字数控制策略与阶段五、六一致：只下限不限上限！
[注意] 如用户反馈涉及大纲结构变更，必须先通过 outline-agent 更新 outline.json，再执行优化！
[注意] 【文件锁定】用户确认通过后，调用 lock_proposal_files 锁定所有正文 .md 文件，后续阶段和 optimizer-agent 不得修改！

【阶段八：合并导出 操作规范】
1. 读取 metadata.json 确认项目状态为"审查优化全部完成"，确认 proposal_files_locked 为 true
2. 调用 check_export_prerequisites(workspace_path) 校验前置条件：
   - outline.json 存在且有效
   - 所有 write_content: true 的节点有对应 .md 文件
   - final_document_file/ 和 images/ 目录可创建
   - 环境依赖检测：python-docx/Pillow/python-markdown（必需，缺失则阻断）、mermaid-cli/mmdc（可选，缺失启用降级）
3. 调用 get_merge_order(workspace_path) 获取深度优先合并顺序列表
4. 调用 generate_chart_mapping(workspace_path) 获取 chart_id → 图题编号/PNG 路径映射
5. 调用 merge_proposal(workspace_path) 主控直接执行合并（无需调度子智能体）
   函数内部执行：
   a) 按合并顺序读取所有正文 .md 文件
   b) 按大纲顺序合并 → 生成 merged_proposal_raw.md（保留原 Mermaid 代码块）
   c) 提取 Mermaid 代码块，按 chart_id 匹配 → 生成 charts_inventory.json
   d) 统一字数统计口径（参考 export_rules.md 8.5 节）和图表数 → 生成 merge_stats.json（含合并耗时）
   e) 返回合并结果统计（章节数、字数、图表清单、异常记录、耗时）
6. 主控 Agent 调用 render_mermaid.py 渲染 PNG（通过 RunCommand）
   输入：merged_proposal_raw.md → 输出：merged_proposal.md + images/*.png
   [注意] 主控 Agent 需将 chart_mapping 写入 final_document_file/_chart_mapping.json 后传给脚本
   [注意] 推荐使用 --stats-output 参数直接写 _render_stats.json，规避 PowerShell stdout 重定向问题
   [注意] mermaid-cli 未安装时自动触发占位图降级，不阻断流程
7. 主控 Agent 调用 md_to_docx.py 转换 Word（通过 RunCommand）
   输入：merged_proposal.md → 输出：<日期>_<项目名称>_技术方案.docx
   [注意] Word 标题自动编号：标题1无编号、标题2 第X章、标题3 X.X、标题4 X.X.X
8. 调用 generate_merge_report(workspace_path, export_stats) 生成 merge_report.md
   [注意] export_stats 可选，缺失时自动从 merge_stats.json 和 _render_stats.json 汇总
   [注意] 报告生成后自动回填 merge_report.md 自身大小
9. 调用 update_metadata_status(workspace_path, "合并导出完成") 更新项目状态
10. 通知用户导出完成（提供 Word 文档路径和报告路径）
[注意] 图表渲染失败不阻断导出流程，采用三级降级方案处理（保留代码块→占位图→文字描述）
[注意] 所有产出文件仅写入 final_document_file/ 目录，不修改已锁定的正文文件
[注意] 前置条件不满足时（proposal_files_locked != true），拒绝执行并提示用户
[注意] 阶段八全部由主控 Agent 直接完成，不调度子智能体（已取消 merge-agent）！
[注意] 合并、统计由 merge_proposal 函数完成；渲染、Word 转换由主控通过 RunCommand 调用脚本完成！
[注意] 字数统计口径统一（参考 export_rules.md 8.5 节）：不计入标题、Mermaid 代码块、图题、图片引用
[注意] 图表编号格式：图 <层级1>-<层级2>-<层级N>-<图表序号>（如 图 1-1-4-1）
[注意] Markdown 中不包含硬编码编号，由 md_to_docx.py 自动添加

【操作注意事项】
- 禁止删除关键配置文件（metadata.json、Supplementary_info.md、outline.json）
- 每阶段完成后需更新 metadata.json 的项目状态
"""


def emit_hook_output(additional_context):
    """输出 hook 协议要求的 JSON（SessionStart → additionalContext 注入）"""
    result = {
        'hookSpecificOutput': {
            'hookEventName': 'SessionStart',
            'additionalContext': additional_context
        }
    }
    output = json.dumps(result, ensure_ascii=False)
    print(output)
    return len(output)


def main():
    # stdout 强制重配置为 UTF-8（兼容未设置 PYTHONUTF8 的机器，
    # 保证中文上下文在管道/重定向场景下无损输出）
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    start_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    log(f'=== SessionStart hook 触发 [{start_ts}] ===')
    log(f'pid={os.getpid()} cwd={os.getcwd()!r}')
    log(f'argv={sys.argv!r}')

    # 环境快照：记录全部变量名（仅名称，避免泄露敏感值）与关键变量值，
    # 用于诊断 Trae 的 hooks 调用上下文（cwd/env 与终端是否一致）。
    # 安全规则：名称含 TOKEN/SECRET/KEY/PASSWORD/REDENTIAL 的变量只记名称不记值
    _SENSITIVE_MARKS = ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')
    try:
        env_names = sorted(os.environ.keys())
        interesting = {}
        for key in env_names:
            ku = key.upper()
            if ku.startswith(('TRAE', 'CLAUDE', 'CURSOR', 'VSCODE', 'AGENT')) or \
                    key in ('COMSPEC', 'PSModulePath', 'TERM', 'OS', 'NUMBER_OF_PROCESSORS'):
                if any(m in ku for m in _SENSITIVE_MARKS):
                    interesting[key] = '<已脱敏>'
                else:
                    interesting[key] = os.environ.get(key, '')[:500]
        log(f'env_var_count={len(env_names)}')
        log(f'env_relevant={json.dumps(interesting, ensure_ascii=False)}')
        log(f'env_all_names={",".join(env_names)}')
    except Exception as e:
        log(f'env 快照记录失败: {type(e).__name__}: {e}')

    # stdin 协议数据读取（字节级容错解码）
    stdin_text, stdin_raw = read_stdin_raw()
    log(f'stdin_bytes={len(stdin_raw)}')
    log(f'stdin_text={stdin_text[:2048]!r}')

    parse_ok = False
    stdin_json = {}
    if stdin_text.strip():
        try:
            stdin_json = json.loads(stdin_text)
            parse_ok = True
            log(f'stdin_json_keys={list(stdin_json.keys()) if isinstance(stdin_json, dict) else type(stdin_json).__name__}')
        except json.JSONDecodeError as e:
            log(f'stdin JSON 解析失败（不影响上下文注入）: {e}')
    else:
        log('stdin 为空（不影响上下文注入）')

    try:
        output_len = emit_hook_output(build_additional_context())
        log(f'hook 执行成功: stdin_parse_ok={parse_ok} output_chars={output_len}')
        log(f'=== SessionStart hook 结束（exit 0） ===')
        sys.exit(0)
    except Exception:
        # 兜底：即使上下文构造/输出异常，也输出合法 JSON 并正常退出，
        # 避免阻塞会话启动；异常详情写入日志供排查
        log(f'hook 主流程异常:\n{traceback.format_exc()}')
        try:
            fallback = {
                'hookSpecificOutput': {
                    'hookEventName': 'SessionStart',
                    'additionalContext': '【BidGenie Flow】项目规范注入异常，详见 .trae/hooks_logs/session_start.log'
                }
            }
            print(json.dumps(fallback, ensure_ascii=False))
        except Exception:
            pass
        log(f'=== SessionStart hook 异常结束（exit 0，降级输出） ===')
        sys.exit(0)


if __name__ == '__main__':
    main()
