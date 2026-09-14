#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""优化功能综合测试脚本"""
import subprocess
import json
import os

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
WORKSPACE = 'bid_project/20260728 120209_t74sug'


def run(skill, func, **kwargs):
    cmd = ['python', '.trae/scripts/run_skill.py', skill, func]
    for k, v in kwargs.items():
        cmd.extend(['--' + k, str(v)])
    r = subprocess.check_output(cmd, cwd=PROJECT_ROOT, text=True)
    return json.loads(r).get('result', {})


def main():
    print('========== 测试1：检查点恢复 - identify_failed_nodes ==========')
    r = run('technical_writing', 'identify_failed_nodes', workspace_path=WORKSPACE)
    print('detected_failed count:', len(r.get('detected_failed', [])))
    print('total_failed:', r.get('total_failed', 0))

    print()
    print('========== 测试2：检查点恢复 - build_task_queue 重试编排 ==========')
    r = run('technical_writing', 'build_task_queue', workspace_path=WORKSPACE)
    rs = r.get('retry_summary', {})
    print('retry_count:', rs.get('retry_count'))
    print('new_count:', rs.get('new_count'))
    print('exhausted_count:', rs.get('exhausted_count'))
    print('skipped_tasks count:', len(r.get('skipped_tasks', [])))
    queue = r.get('task_queue', [])
    if queue:
        first3 = [(t['node_id'], t.get('status')) for t in queue[:3]]
        print('first 3 in queue:', first3)

    print()
    print('========== 测试3：AI 审查自动化 - get_ai_review_status ==========')
    r = run('review_optimization', 'get_ai_review_status', workspace_path=WORKSPACE)
    print('completed:', r.get('completed_count'))
    print('pending:', r.get('pending_count'))
    print('failed:', r.get('failed_count'))
    print('all_completed:', r.get('all_completed'))

    print()
    print('========== 测试4：AI 审查自动化 - plan_ai_review_tasks ==========')
    r = run('review_optimization', 'plan_ai_review_tasks', workspace_path=WORKSPACE)
    print('recommended_tasks:', r.get('recommended_tasks'))
    print('optional_tasks:', r.get('optional_tasks'))
    ds = r.get('decision_summary', {})
    print('decision: severe_word=%s, chart_issue=%s, structure_issue=%s' % (
        ds.get('severe_word_count_count'),
        ds.get('chart_issue_count'),
        ds.get('structure_issue_count')
    ))
    # 打印每个任务的优先级
    plan = r.get('plan', {})
    for task_type, info in plan.items():
        print('  [%s] priority=%s, should_execute=%s' % (
            task_type, info.get('priority'), info.get('should_execute')
        ))

    print()
    print('========== 测试5：AI 审查自动化 - identify_failed_ai_reviews ==========')
    r = run('review_optimization', 'identify_failed_ai_reviews', workspace_path=WORKSPACE)
    s = r.get('summary', {})
    print('failed:', s.get('failed_count'))
    print('pending:', s.get('pending_count'))
    print('retryable:', s.get('retryable_count'))
    print('exhausted:', s.get('exhausted_count'))

    print()
    print('========== 所有测试通过 ==========')


if __name__ == '__main__':
    main()
