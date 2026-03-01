#!/usr/bin/env python3
"""
image_ref_harvester - 图片参考素材收集工具 (Page Mining Mode with Attribution Check)
通过 Brave Search 获取源页面，进行摄影师归属校验后挖掘高质量原图
"""

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote, urljoin

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

MIN_FILE_SIZE = 10 * 1024
BRAVE_API_ENDPOINT = "https://api.search.brave.com/res/v1/images/search"
VALID_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.avif'}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CURL_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 30

HIGH_QUALITY_INDICATORS = ['original', 'master', '2000', '3000', '4k', 'large', 'full', 'max', '2400', '1600']
NEGATIVE_KEYWORDS = ['-tickets', '-poster', '-banner', '-template', '-stock', '-advertisement']

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_brave_api_key():
    key = os.environ.get('BRAVE_API_KEY')
    if not key:
        log("错误：未设置 BRAVE_API_KEY 环境变量")
        sys.exit(1)
    return key

def build_search_query(args):
    """构建搜索查询词，强化摄影师署名意图"""
    parts = []
    
    if args.photographer:
        parts.append(f'"{args.photographer}"')
        parts.append(f'("photographed by" OR "photography by" OR "photo by" OR "shot by") "{args.photographer}"')
    
    parts.append(args.subject)
    
    if args.theme:
        parts.append(args.theme)
    if args.clothing:
        parts.append(args.clothing)
    if args.style_tags:
        tags = args.style_tags.split(',')[:2]
        parts.extend(tags)
    
    parts.extend(NEGATIVE_KEYWORDS)
    
    query = ' '.join(parts)
    log(f"搜索查询: {query}")
    return query

def search_pages(query, api_key, max_pages=50):
    headers = {
        'Accept': 'application/json',
        'X-Subscription-Token': api_key
    }
    
    pages = []
    offset = 0
    
    while len(pages) < max_pages and offset < 100:
        url = f"{BRAVE_API_ENDPOINT}?q={urllib.parse.quote(query)}&count=50&offset={offset}&safesearch=off"
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                encoding = response.headers.get('Content-Encoding', '')
                if 'gzip' in encoding:
                    data = gzip.decompress(response.read())
                else:
                    data = response.read()
                
                json_data = json.loads(data.decode('utf-8'))
                results = json_data.get('results', [])
                
                for r in results:
                    source_url = r.get('source') or r.get('url', '')
                    if source_url and not source_url.startswith('data:'):
                        pages.append({
                            'source_page_url': source_url,
                            'title': r.get('title', ''),
                            'publisher': r.get('publisher', ''),
                        })
                
                if len(results) < 50:
                    break
                offset += len(results)
                    
        except Exception as e:
            log(f"搜索出错: {e}")
            break
    
    log(f"搜索返回 {len(pages)} 个源页面")
    return pages

def rank_pages_by_preferred_domain(pages, prefer_domains):
    if not prefer_domains:
        return pages
    
    domains = [d.strip().lower() for d in prefer_domains.split(',')]
    seen = set()
    ranked = []
    
    for domain in domains:
        for page in pages:
            if domain in page['source_page_url'].lower() and page['source_page_url'] not in seen:
                ranked.append(page)
                seen.add(page['source_page_url'])
    
    for page in pages:
        if page['source_page_url'] not in seen:
            ranked.append(page)
            seen.add(page['source_page_url'])
    
    return ranked

def fetch_html_with_curl(url, timeout=CURL_TIMEOUT):
    try:
        cmd = ['curl', '-L', '-s', '--max-time', str(timeout), 
               '-A', USER_AGENT, '--compressed', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except:
        pass
    return None

def extract_readable_text(html):
    """从 HTML 提取可读文本（去掉 script/style）"""
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def check_photographer_attribution(html_text, photographer_name, strict_mode=True):
    """
    检查摄影师归属
    strict_mode=True: 需要署名短语或 photographer 共现
    strict_mode=False: 仅包含名字即可
    返回: (has_name, has_attribution)
    """
    if not photographer_name:
        return True, True
    
    text_lower = html_text.lower()
    name_lower = photographer_name.lower()
    
    # 1. 检查是否包含摄影师名字
    has_name = name_lower in text_lower
    
    if not has_name:
        return False, False
    
    # 非严格模式：只要有名字就通过
    if not strict_mode:
        return True, True
    
    # 2. 严格模式：检查署名短语
    attribution_patterns = [
        rf'photographed\s+by\s+{re.escape(name_lower)}',
        rf'photography\s+by\s+{re.escape(name_lower)}',
        rf'photo\s+by\s+{re.escape(name_lower)}',
        rf'shot\s+by\s+{re.escape(name_lower)}',
    ]
    
    has_attribution_phrase = any(
        re.search(pattern, text_lower) 
        for pattern in attribution_patterns
    )
    
    # 3. 检查 "photographer" 与名字同页共现
    has_photographer_word = 'photographer' in text_lower
    cooccurrence = has_photographer_word and name_lower in text_lower
    
    has_attribution = has_attribution_phrase or cooccurrence
    
    return True, has_attribution

def extract_meta_image(html, base_url):
    images = []
    og_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if og_match:
        images.append(('og:image', og_match.group(1)))
    tw_match = re.search(r'<meta[^>]*name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if tw_match:
        images.append(('twitter:image', tw_match.group(1)))
    og_match2 = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', html, re.IGNORECASE)
    if og_match2:
        images.append(('og:image', og_match2.group(1)))
    return images

def extract_preload_images(html, base_url):
    images = []
    pattern = r'<link[^>]*rel=["\']preload["\'][^>]*as=["\']image["\'][^>]*href=["\']([^"\']+)["\']'
    for match in re.finditer(pattern, html, re.IGNORECASE):
        images.append(('preload', match.group(1)))
    pattern2 = r'<link[^>]*as=["\']image["\'][^>]*rel=["\']preload["\'][^>]*href=["\']([^"\']+)["\']'
    for match in re.finditer(pattern2, html, re.IGNORECASE):
        images.append(('preload', match.group(1)))
    return images

def extract_img_tags(html, base_url):
    images = []
    srcset_pattern = r'<img[^>]*srcset=["\']([^"\']+)["\']'
    for match in re.finditer(srcset_pattern, html, re.IGNORECASE):
        srcset = match.group(1)
        candidates = []
        for part in srcset.split(','):
            part = part.strip()
            url_size = part.rsplit(' ', 1)
            if len(url_size) == 2:
                url, size = url_size
                size_num = re.search(r'(\d+)', size)
                if size_num:
                    candidates.append((int(size_num.group(1)), url.strip()))
        if candidates:
            candidates.sort(reverse=True)
            images.append(('srcset-max', candidates[0][1]))
    
    src_pattern = r'<img[^>]*src=["\']([^"\']+)["\']'
    for match in re.finditer(src_pattern, html, re.IGNORECASE):
        src = match.group(1)
        if not src.startswith('data:'):
            images.append(('img-src', src))
    return images

def extract_jsonld_images(html, base_url):
    images = []
    jsonld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    for match in re.finditer(jsonld_pattern, html, re.IGNORECASE | re.DOTALL):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                if 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        images.append(('jsonld-image', img))
                    elif isinstance(img, list) and img:
                        images.append(('jsonld-image', img[0]))
                    elif isinstance(img, dict) and 'url' in img:
                        images.append(('jsonld-image', img['url']))
        except:
            pass
    return images

def normalize_url(url, base_url):
    if not url:
        return None
    url = url.strip()
    if url.startswith('http://') or url.startswith('https://'):
        return url
    if url.startswith('data:'):
        return None
    try:
        return urljoin(base_url, url)
    except:
        return None

def extract_images_from_page(html, base_url, max_images=20):
    all_images = []
    seen_urls = set()
    
    extractors = [
        extract_meta_image,
        extract_preload_images,
        extract_img_tags,
        extract_jsonld_images,
    ]
    
    priority = 0
    for extractor in extractors:
        for source_type, url in extractor(html, base_url):
            normalized = normalize_url(url, base_url)
            if normalized and normalized not in seen_urls:
                lower_url = normalized.lower()
                if any(x in lower_url for x in ['favicon', 'icon-', 'logo-', 'avatar', 'thumb_', '_thumb']):
                    continue
                all_images.append({
                    'url': normalized,
                    'source_type': source_type,
                    'priority': priority
                })
                seen_urls.add(normalized)
                if len(all_images) >= max_images * 2:
                    break
        priority += 1
        if len(all_images) >= max_images * 2:
            break
    
    return all_images[:max_images]

def score_image_url(url):
    score = 0
    lower_url = url.lower()
    for i, indicator in enumerate(HIGH_QUALITY_INDICATORS):
        if indicator in lower_url:
            score += (len(HIGH_QUALITY_INDICATORS) - i) * 10
    if any(lower_url.endswith(ext) for ext in ['.jpg', '.jpeg']):
        score += 5
    elif lower_url.endswith('.png'):
        score += 3
    return score

def head_check_image(url, timeout=10):
    try:
        req = urllib.request.Request(url, method='HEAD', headers={
            'User-Agent': USER_AGENT,
            'Accept': 'image/*,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            content_type = response.headers.get('Content-Type', '')
            content_length = response.headers.get('Content-Length')
            is_image = content_type.startswith('image/')
            length = int(content_length) if content_length else 0
            return is_image, length
    except:
        return False, 0

def get_file_extension_from_url(url):
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1].lower()
        if ext in VALID_IMAGE_EXTENSIONS:
            return ext
    except:
        pass
    return '.jpg'

def calculate_sha1(filepath):
    sha1_hash = hashlib.sha1()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha1_hash.update(chunk)
    return sha1_hash.hexdigest()

def get_image_dimensions_sips(filepath):
    try:
        result = subprocess.run(
            ['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(filepath)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            output = result.stdout
            width_match = re.search(r'pixelWidth:\s*(\d+)', output)
            height_match = re.search(r'pixelHeight:\s*(\d+)', output)
            if width_match and height_match:
                return int(width_match.group(1)), int(height_match.group(1))
    except:
        pass
    return None, None

def download_image(url, filepath, timeout=DOWNLOAD_TIMEOUT):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'image/*,*/*;q=0.8',
            'Referer': 'https://www.google.com/'
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            content_type = response.headers.get('Content-Type', '')
            if not content_type.startswith('image/'):
                return False, 'fail_non_image', 0
            data = response.read()
            file_size = len(data)
            with open(filepath, 'wb') as f:
                f.write(data)
            return True, None, file_size
    except urllib.error.HTTPError as e:
        error_code = f'fail_{e.code}' if e.code in (403, 404) else 'fail_other'
        return False, error_code, 0
    except:
        return False, 'fail_other', 0

def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name.strip('_')[:50]

def generate_pack_name(args):
    parts = []
    if args.photographer:
        parts.append(sanitize_filename(args.photographer))
    parts.append(sanitize_filename(args.subject))
    if args.theme:
        parts.append(sanitize_filename(args.theme))
    base_name = '_'.join(parts) if parts else 'ref_pack'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{base_name}_{timestamp}"

def main():
    parser = argparse.ArgumentParser(description='图片参考素材收集工具 (Page Mining with Attribution Check)')
    parser.add_argument('--photographer', help='摄影师名称')
    parser.add_argument('--subject', required=True, help='主题（必填）')
    parser.add_argument('--theme', help='主题风格')
    parser.add_argument('--clothing', help='服装类型')
    parser.add_argument('--style_tags', help='风格标签（逗号分隔）')
    parser.add_argument('--count', type=int, default=40, help='目标下载数量（默认40）')
    parser.add_argument('--min_short_edge', type=int, default=800, help='最小短边像素（默认800）')
    parser.add_argument('--max_pages_to_mine', type=int, default=25, help='最大挖图页面数（默认25）')
    parser.add_argument('--max_images_per_page', type=int, default=20, help='每页最大候选图数（默认20）')
    parser.add_argument('--out_root', default='~/Pictures/openclaw_refs', help='输出根目录')
    parser.add_argument('--prefer_domains', help='优先域名（逗号分隔）')
    parser.add_argument('--attribution_check', choices=['on', 'off'], default='on', help='摄影师归属校验（默认on）')
    parser.add_argument('--strict_attribution', choices=['on', 'off'], default='off', help='严格署名要求（默认off，仅检查名字存在）')
    
    args = parser.parse_args()
    
    api_key = get_brave_api_key()
    query = build_search_query(args)
    
    log("=" * 60)
    log("阶段1: 搜索源页面...")
    pages = search_pages(query, api_key, max_pages=args.max_pages_to_mine * 2)
    pages = rank_pages_by_preferred_domain(pages, args.prefer_domains)
    pages = pages[:args.max_pages_to_mine]
    
    log(f"将处理 {len(pages)} 个页面")
    
    out_root = Path(args.out_root).expanduser()
    pack_name = generate_pack_name(args)
    pack_dir = out_root / pack_name
    manifest_dir = pack_dir / '00_manifest'
    images_dir = pack_dir / '01_images'
    manifest_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    
    log(f"输出目录: {pack_dir}")
    log(f"最小短边要求: {args.min_short_edge}px")
    log(f"归属校验: {args.attribution_check} (严格模式: {args.strict_attribution})")
    if args.photographer:
        log(f"目标摄影师: {args.photographer}")
    log("=" * 60)
    
    stats = {
        'searched_results': len(pages),
        'pages_skipped_no_name': 0,
        'pages_skipped_no_attribution': 0,
        'pages_mined_passed_attribution': 0,
        'pages_failed': 0,
        'images_found_total': 0,
        'images_head_pass': 0,
        'download_attempted': 0,
        'downloaded_ok': 0,
        'removed_too_small': 0,
        'fail_403': 0,
        'fail_404': 0,
        'fail_non_image': 0,
        'fail_too_small': 0,
        'fail_other': 0,
    }
    
    sources_rows = []
    metadata_rows = []
    date_accessed = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    downloaded_sha1s = set()
    
    strict_mode = args.strict_attribution == 'on'
    
    for page_idx, page in enumerate(pages):
        if stats['downloaded_ok'] >= args.count:
            break
        
        source_url = page['source_page_url']
        domain = urlparse(source_url).netloc
        
        log(f"\n[{page_idx+1}/{len(pages)}] 处理页面: {domain}")
        log(f"    URL: {source_url[:80]}...")
        
        html = fetch_html_with_curl(source_url)
        if not html:
            stats['pages_failed'] += 1
            log(f"    ❌ 抓取失败")
            continue
        
        # 归属校验
        if args.attribution_check == 'on' and args.photographer:
            readable_text = extract_readable_text(html)
            has_name, has_attribution = check_photographer_attribution(
                readable_text, args.photographer, strict_mode=strict_mode
            )
            
            if not has_name:
                stats['pages_skipped_no_name'] += 1
                log(f"    ⏭️ 跳过: 页面无摄影师名字 '{args.photographer}'")
                continue
            
            if strict_mode and not has_attribution:
                stats['pages_skipped_no_attribution'] += 1
                log(f"    ⏭️ 跳过: 有名字但无明确署名信息")
                continue
            
            stats['pages_mined_passed_attribution'] += 1
            log(f"    ✅ 归属校验通过" + (" (严格)" if strict_mode and has_attribution else " (宽松-仅名字)"))
        else:
            stats['pages_mined_passed_attribution'] += 1
        
        candidates = extract_images_from_page(html, source_url, args.max_images_per_page)
        stats['images_found_total'] += len(candidates)
        
        log(f"    找到 {len(candidates)} 个候选图片")
        
        if not candidates:
            continue
        
        for c in candidates:
            c['score'] = score_image_url(c['url'])
        candidates.sort(key=lambda x: (-x['score'], x['priority']))
        
        page_success = False
        for candidate in candidates:
            if stats['downloaded_ok'] >= args.count:
                break
            
            img_url = candidate['url']
            
            is_image, content_length = head_check_image(img_url)
            if not is_image:
                continue
            
            stats['images_head_pass'] += 1
            
            if content_length > 100 * 1024:
                log(f"    优先: 大文件 {content_length//1024}KB")
            
            stats['download_attempted'] += 1
            
            ext = get_file_extension_from_url(img_url)
            temp_path = images_dir / f"temp_{stats['download_attempted']:04d}{ext}"
            
            log(f"    尝试下载: {img_url[:60]}...")
            success, error_code, file_size = download_image(img_url, temp_path)
            
            if not success:
                stats[error_code] = stats.get(error_code, 0) + 1
                log(f"      ❌ 下载失败: {error_code}")
                continue
            
            if file_size <= MIN_FILE_SIZE:
                stats['fail_too_small'] += 1
                stats['removed_too_small'] += 1
                log(f"      ❌ 文件过小 ({file_size} bytes)")
                temp_path.unlink(missing_ok=True)
                continue
            
            width, height = get_image_dimensions_sips(temp_path)
            if width and height:
                short_edge = min(width, height)
                if short_edge < args.min_short_edge:
                    stats['removed_too_small'] += 1
                    log(f"      ❌ 短边 {short_edge}px < {args.min_short_edge}px")
                    temp_path.unlink(missing_ok=True)
                    continue
                log(f"      ✅ 通过: {width}x{height} ({file_size//1024}KB)")
            else:
                log(f"      ⚠️ 无法获取尺寸，保留 (未知分辨率)")
                width, height = 'unknown', 'unknown'
            
            sha1_hash = calculate_sha1(temp_path)
            if sha1_hash in downloaded_sha1s:
                log(f"      ⚠️ 重复图片，跳过")
                temp_path.unlink(missing_ok=True)
                continue
            
            downloaded_sha1s.add(sha1_hash)
            
            final_filename = f"{stats['downloaded_ok'] + 1:03d}{ext}"
            final_path = images_dir / final_filename
            temp_path.rename(final_path)
            
            stats['downloaded_ok'] += 1
            page_success = True
            
            sources_rows.append({
                'source_page_url': source_url,
                'image_url': img_url,
                'title': page['title'],
                'publisher': page['publisher'],
                'date_accessed': date_accessed
            })
            
            metadata_rows.append({
                'filename': final_filename,
                'photographer': args.photographer or '',
                'subject': args.subject,
                'theme': args.theme or '',
                'clothing': args.clothing or '',
                'style_tags': args.style_tags or '',
                'sha1': sha1_hash,
                'notes': f'{file_size} bytes',
                'width': str(width) if width else 'unknown',
                'height': str(height) if height else 'unknown'
            })
            
            break
        
        if not page_success:
            log(f"    该页面无图片通过质量检查")
        
        time.sleep(0.5)
    
    log("\n" + "=" * 60)
    log("写入 CSV 文件...")
    
    with open(manifest_dir / 'sources.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['source_page_url', 'image_url', 'title', 'publisher', 'date_accessed'])
        writer.writeheader()
        writer.writerows(sources_rows)
    
    with open(manifest_dir / 'metadata.csv', 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['filename', 'photographer', 'subject', 'theme', 'clothing', 'style_tags', 'sha1', 'notes', 'width', 'height']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metadata_rows)
    
    readme_content = f"""Image Reference Pack (Page Mining with Attribution Check)
=========================================================
Pack Name: {pack_name}
Generated: {date_accessed}

Query
-----
{query}

Parameters
----------
  photographer: {args.photographer or 'N/A'}
  subject: {args.subject}
  theme: {args.theme or 'N/A'}
  clothing: {args.clothing or 'N/A'}
  style_tags: {args.style_tags or 'N/A'}
  count: {args.count}
  min_short_edge: {args.min_short_edge}px
  max_pages_to_mine: {args.max_pages_to_mine}
  max_images_per_page: {args.max_images_per_page}
  prefer_domains: {args.prefer_domains or 'N/A'}
  out_root: {args.out_root}
  attribution_check: {args.attribution_check}
  strict_attribution: {args.strict_attribution}

Attribution Statistics
----------------------
  pages_skipped_no_name: {stats['pages_skipped_no_name']}
  pages_skipped_no_attribution: {stats['pages_skipped_no_attribution']}
  pages_mined_passed_attribution: {stats['pages_mined_passed_attribution']}

Page Mining Statistics
----------------------
  pages_mined: {stats['pages_mined_passed_attribution']}
  pages_failed: {stats['pages_failed']}
  images_found_total: {stats['images_found_total']}
  images_head_pass: {stats['images_head_pass']}

Download Statistics
-------------------
  download_attempted: {stats['download_attempted']}
  downloaded_ok: {stats['downloaded_ok']}
  removed_too_small: {stats['removed_too_small']}
  fail_403: {stats['fail_403']}
  fail_404: {stats['fail_404']}
  fail_non_image: {stats['fail_non_image']}
  fail_too_small: {stats['fail_too_small']}
  fail_other: {stats['fail_other']}

Files
-----
  01_images/        - {stats['downloaded_ok']} image files
  00_manifest/sources.csv   - Image source URLs
  00_manifest/metadata.csv  - File metadata with dimensions

"""
    
    with open(manifest_dir / 'README.txt', 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    log("=" * 60)
    log("下载完成!")
    log(f"包路径: {pack_dir}")
    log(f"归属校验跳过: {stats['pages_skipped_no_name']} (无名字) / {stats['pages_skipped_no_attribution']} (无署名)")
    log(f"通过归属校验: {stats['pages_mined_passed_attribution']}")
    log(f"候选图片: {stats['images_found_total']} 个")
    log(f"HEAD 通过: {stats['images_head_pass']} 个")
    log(f"成功下载: {stats['downloaded_ok']}/{args.count}")
    log(f"因质量删除: {stats['removed_too_small']}")
    log("")
    log("失败原因统计:")
    log(f"  fail_403: {stats['fail_403']}")
    log(f"  fail_404: {stats['fail_404']}")
    log(f"  fail_non_image: {stats['fail_non_image']}")
    log(f"  fail_too_small: {stats['fail_too_small']}")
    log(f"  fail_other: {stats['fail_other']}")
    log("=" * 60)
    
    print(f"\nPACK_PATH:{pack_dir}")

if __name__ == '__main__':
    main()
