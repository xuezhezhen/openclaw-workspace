# image_ref_harvester (Page Mining Mode)

本机执行的图片参考素材收集工具。采用 **Page Mining 模式**：通过 Brave Search 获取源页面，再从页面挖掘高质量原图下载。

## 工作原理

1. **搜索阶段**: Brave Search 获取源页面 URL (source_page_url)
2. **挖图阶段**: 访问每个源页面，提取高质量图片
3. **筛选阶段**: 按分辨率/文件大小过滤，自动补齐数量

## 位置

~/.openclaw/skills/image_ref_harvester/

## 用法

### 方式一：自然语言（推荐）⭐

```bash
cd ~/.openclaw/skills/image_ref_harvester
./parse_and_run.py '自然语言描述'
```

### 方式二：命令行参数

```bash
cd ~/.openclaw/skills/image_ref_harvester
./download_refs.py [参数]
```

## 参数表

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `photographer` | 可选 | - | 摄影师名称 |
| `subject` | **必填** | - | 主题 |
| `theme` | 可选 | - | 主题风格 |
| `clothing` | 可选 | - | 服装类型 |
| `style_tags` | 可选 | - | 风格标签，逗号分隔 |
| `count` | 可选 | 40 | 目标下载数量 |
| `min_short_edge` | 可选 | **800** | 最小短边像素 |
| `max_pages_to_mine` | 可选 | 25 | 最大挖图页面数 |
| `max_images_per_page` | 可选 | 20 | 每页最大候选图数 |
| `out_root` | 可选 | ~/Pictures/openclaw_refs | 输出根目录 |
| `prefer_domains` | 可选 | - | 优先域名 |

## 自然语言解析规则

| 参数 | 识别关键词 | 示例 |
|------|-----------|------|
| **photographer** | `XXX 的`, `摄影师 XXX` | "Tim Walker 的" |
| **subject** | `搜 XXX`, `找 XXX` | "搜 fashion editorial" |
| **theme** | `主题 XXX` | "主题 surreal fairytale" |
| **clothing** | `服装 XXX` | "服装 couture gown" |
| **style_tags** | `风格 XXX` | "风格 high fashion,theatrical" |
| **count** | `X张` | "30张" |
| **min_short_edge** | `最短边>=1600`, `1600px` | "最短边>=1600" |
| **prefer_domains** | `优先 XXX` | "优先 vogue.com" |

## 挖图策略

### 图片来源优先级

1. `<meta property="og:image">`
2. `<meta name="twitter:image">`
3. `<link rel="preload" as="image">`
4. `<img srcset>`（取最大尺寸）
5. `<img src>`
6. JSON-LD 中的 image 字段

### 质量选择

- URL 含 `original/master/2000/3000/4k/large` 优先
- HEAD 检查 content-length，优先大文件
- 下载后检查 min_short_edge 与文件大小

## 示例

### 示例 1：完整描述

```bash
./parse_and_run.py '给我搜 Tim Walker 的 fashion editorial，主题 surreal fairytale，服装 couture gown，风格 high fashion/theatrical/pastel，30张，最短边>=1600，优先 vogue.com 和 showstudio.com'
```

解析结果：
- photographer: Tim Walker
- subject: fashion editorial
- theme: surreal fairytale
- clothing: couture gown
- style_tags: high fashion,theatrical,pastel
- count: 30
- min_short_edge: 1600
- prefer_domains: vogue.com,showstudio.com

### 示例 2：简洁模式

```bash
./parse_and_run.py '搜 street style 摄影，50张'
```

### 示例 3：高分辨率要求

```bash
./parse_and_run.py '找 Helmut Newton 的黑白 portrait，最短边 2000px，20张'
```

## 输出结构

```
<out_root>/<pack_name>/
  00_manifest/
    sources.csv      # 图片来源（记录最终下载的高分图 URL）
    metadata.csv     # 文件元数据（含 width/height）
    README.txt       # 详细统计信息
  01_images/         # 下载的图片
    001.jpg
    002.png
    ...
```

### CSV 字段

**sources.csv:** `source_page_url`, `image_url`, `title`, `publisher`, `date_accessed`

**metadata.csv:** `filename`, `photographer`, `subject`, `theme`, `clothing`, `style_tags`, `sha1`, `notes`, `width`, `height`

### README 统计信息

- Query: 实际搜索查询字符串
- Parameters: 完整参数列表
- Page Mining Statistics: pages_mined, pages_failed, images_found_total, images_head_pass
- Download Statistics: downloaded_ok, removed_too_small, 各类 fail 统计

## 依赖

- Python 3.8+
- curl（用于页面抓取）
- sips（macOS 内置，用于获取图片尺寸）
- 环境变量 `BRAVE_API_KEY`

## 安全

- BRAVE_API_KEY 仅通过环境变量读取
- 使用 HTTPS + SSL 证书验证跳过（用于图片下载）
