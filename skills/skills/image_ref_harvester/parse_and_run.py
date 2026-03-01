#!/usr/bin/env python3
"""
natural language parser for image_ref_harvester (Page Mining with Attribution Check)
解析自然语言输入，提取参数并执行下载
"""

import json
import re
import subprocess
import sys
from pathlib import Path

def parse_natural_language(text):
    """
    解析自然语言，提取参数
    """
    text_clean = text
    text_lower = text.lower()
    params = {
        'photographer': None,
        'subject': None,
        'theme': None,
        'clothing': None,
        'style_tags': None,
        'count': 40,
        'min_short_edge': 800,  # 默认 800px
        'max_pages_to_mine': 25,
        'max_images_per_page': 20,
        'prefer_domains': None,
        'out_root': '~/Pictures/openclaw_refs'
    }
    
    # 1. 提取 min_short_edge（最短边分辨率要求）
    min_edge_patterns = [
        r'(?:最短边|short\s*edge|min(?:imum)?)\s*[:>=]?\s*(\d{3,4})\s*(?:px|像素)?',
        r'(\d{3,4})\s*(?:px|像素)\s*(?:最短边|short\s*edge)?',
    ]
    for pattern in min_edge_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            params['min_short_edge'] = int(match.group(1))
            break
    
    # 2. 提取 count
    count_patterns = [
        r'(\d+)\s*[张个幅]',
        r'count\s*(\d+)',
        r'number\s*(\d+)',
        r'(\d+)\s*(?:images?|photos?)',
    ]
    for pattern in count_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            params['count'] = int(match.group(1))
            break
    
    # 3. 提取 photographer
    photographer_patterns = [
        r'(?:搜|找|搜索|给我|我要|收集)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s*的',
        r'(?:摄影师|photographer)\s*[:\s]+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})',
        r'by\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s*(?:摄影|photo|的)',
    ]
    for pattern in photographer_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            params['photographer'] = match.group(1).strip()
            break
    
    # 4. 提取 prefer_domains
    domain_match = re.search(r'优先\s*[:：]?\s*(.+?)(?:\s*$|\s+(?:输出|保存))', text)
    if not domain_match:
        domain_match = re.search(r'prefer\s*[:\s]+(.+?)(?:\s*$|\s+(?:domain|site))', text, re.IGNORECASE)
    
    if domain_match:
        domain_section = domain_match.group(1)
        domain_section = domain_section.replace('，', ',').replace('、', ',')
        domain_section = domain_section.replace('和', ',').replace('以及', ',')
        domain_list = []
        for d in domain_section.split(','):
            d = d.strip()
            if d and ('.' in d or any(tld in d.lower() for tld in ['com', 'org', 'net', 'io'])):
                domain_list.append(d)
        if domain_list:
            params['prefer_domains'] = ','.join(domain_list)
    
    # 5. 提取 clothing
    clothing_patterns = [
        r'(?:服装|衣服|穿搭|clothing|wear|wearing|dress)\s*[:：]?\s*([^,，.。;；\d]{2,30})',
    ]
    for pattern in clothing_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            params['clothing'] = match.group(1).strip()
            break
    
    # 6. 提取 theme
    theme_patterns = [
        r'(?:主题|theme)\s*[:：]?\s*([^,，.。;；\d]{2,30})',
    ]
    for pattern in theme_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            params['theme'] = match.group(1).strip()
            break
    
    # 7. 提取 style_tags
    style_patterns = [
        r'(?:风格|style)\s*[:：]?\s*([^,，.。;；]+)',
    ]
    for pattern in style_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            tags = match.group(1).strip()
            tags = tags.replace('/', ',').replace('、', ',').replace('，', ',')
            tags = ','.join([t.strip() for t in tags.split(',') if t.strip()])
            if tags:
                params['style_tags'] = tags
            break
    
    # 8. 提取 subject
    if params['photographer']:
        pattern = rf'(?:搜|找|搜索|收集)\s+{re.escape(params["photographer"])}\s*的\s*([^,，.。;；\d]{{3,40}}?)(?:\s*[,，.。;；]|\s+(?:主题|风格|服装|最短边|\d|$))'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            params['subject'] = match.group(1).strip()
    
    if not params['subject']:
        subject_patterns = [
            r'(?:搜|找|搜索|给我|我要|收集)\s+(?:[\w\s]+\s+)?的\s*([^,，.。;；\d]{3,40}?)(?:\s*[,，.。;；]|\s+(?:主题|风格|服装|最短边|photographer|by|\d|$))',
            r'(?:搜|找|搜索|给我|我要|收集)\s+([^,，.。;；\d]{3,40}?)(?:\s*[,，.。;；]|\s+(?:的|主题|风格|服装|最短边|\d|$))',
        ]
        for pattern in subject_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if params['photographer']:
                    candidate = candidate.replace(params['photographer'], '').strip()
                    candidate = re.sub(r'^\s*的\s*', '', candidate)
                if len(candidate) >= 3:
                    params['subject'] = candidate
                    break
    
    if not params['subject']:
        match = re.search(r'([\w\s]{3,30}?)(?:\s+photography|\s+photo|\s+style|\s+editorial)', text, re.IGNORECASE)
        if match:
            params['subject'] = match.group(1).strip()
    
    return params

def generate_summary(params):
    """生成参数摘要"""
    lines = []
    lines.append("📋 参数解析结果：")
    lines.append("")
    
    if params['photographer']:
        lines.append(f"  摄影师: {params['photographer']}")
    
    if params['subject']:
        lines.append(f"  主题: {params['subject']}")
    else:
        lines.append(f"  ⚠️ 主题: 未识别（必须提供）")
    
    if params['theme']:
        lines.append(f"  主题风格: {params['theme']}")
    
    if params['clothing']:
        lines.append(f"  服装: {params['clothing']}")
    
    if params['style_tags']:
        lines.append(f"  风格标签: {params['style_tags']}")
    
    lines.append(f"  数量: {params['count']}张")
    lines.append(f"  最小短边: {params['min_short_edge']}px")
    lines.append(f"  挖图页面数: {params['max_pages_to_mine']}")
    
    if params['prefer_domains']:
        lines.append(f"  优先域名: {params['prefer_domains']}")
    
    lines.append(f"  输出目录: {params['out_root']}")
    lines.append("")
    
    return "\n".join(lines)

def build_command(params):
    """构建命令行参数"""
    cmd = [str(Path(__file__).parent / 'download_refs.py')]
    
    if params['photographer']:
        cmd.extend(['--photographer', params['photographer']])
    
    if params['subject']:
        cmd.extend(['--subject', params['subject']])
    
    if params['theme']:
        cmd.extend(['--theme', params['theme']])
    
    if params['clothing']:
        cmd.extend(['--clothing', params['clothing']])
    
    if params['style_tags']:
        cmd.extend(['--style_tags', params['style_tags']])
    
    cmd.extend(['--count', str(params['count'])])
    cmd.extend(['--min_short_edge', str(params['min_short_edge'])])
    cmd.extend(['--max_pages_to_mine', str(params['max_pages_to_mine'])])
    cmd.extend(['--out_root', params['out_root']])
    
    if params['prefer_domains']:
        cmd.extend(['--prefer_domains', params['prefer_domains']])
    
    return cmd

def main():
    if len(sys.argv) < 2:
        print("用法: python3 parse_and_run.py '自然语言描述'")
        print("\n示例:")
        print('  python3 parse_and_run.py "收集 Tim Walker 的照片，20张，最短边1200"')
        sys.exit(1)
    
    input_text = ' '.join(sys.argv[1:])
    
    print(f"📝 输入: {input_text}")
    print("")
    
    params = parse_natural_language(input_text)
    
    if not params['subject']:
        print("❌ 缺少必填参数: subject (主题)")
        print("\n请提供搜索主题，例如:")
        print('  "搜 fashion editorial"')
        sys.exit(1)
    
    print(generate_summary(params))
    
    print("📊 解析 JSON:")
    print(json.dumps(params, indent=2, ensure_ascii=False))
    print("")
    
    print("确认执行? (y/n): ", end='', flush=True)
    try:
        response = input().strip().lower()
        if response not in ('y', 'yes', '是', '确认'):
            print("已取消")
            sys.exit(0)
    except EOFError:
        print("y (自动确认)")
    
    print("")
    print("🚀 开始执行...")
    print("")
    
    cmd = build_command(params)
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    
    subprocess.run(cmd, env=env)

if __name__ == '__main__':
    import os
    main()
