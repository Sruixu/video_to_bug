#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
video_to_bug.py - 录屏视频一键转 BUG 单工具

用法:
    # 单个视频
    python video_to_bug.py "D:\录屏\加购失败.mp4"
    python video_to_bug.py "D:\录屏\加购失败.mp4" --save

    # 批量处理（整个目录）
    python video_to_bug.py "D:\录屏\" --save
    python video_to_bug.py "D:\录屏\*.mp4" --save

    # GUI 模式（推荐日常使用）
    python video_to_bug_gui.py

工作原理:
    1. 调用 matrix MCP 的 matrix_videos_understand 工具分析视频
    2. 用 AI Prompt 让模型直接输出 BUG 单四段（标题/操作步骤/实际结果/预期结果）
    3. 输出到控制台 + 自动复制到剪贴板（方便直接 Ctrl+V 提交）
    4. 可选保存到 .md 文件，文件名用 BUG 标题
"""

import argparse
import fnmatch
import glob as _glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Windows 终端默认 GBK，强制 UTF-8 输出避免中文报错
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ========== 配置 ==========
MCP_SERVER = "matrix"
MCP_TOOL = "matrix_videos_understand"
MAX_RETRY = 3  # 上游偶发失败时重试次数
RETRY_DELAY = 5  # 重试间隔（秒）
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v", ".3gp", ".wmv"}


# ========== Prompt 模板（精简版）==========
PROMPT_TEMPLATE = """你是一名资深的移动端 APP 测试工程师。请仔细观察这个录屏视频（这是一个 BUG 复现视频），从中提取【BUG 标题】【操作步骤】【实际结果】【预期结果】，用于提交 BUG 单。

## 输出要求（务必言简意赅）

### 1. BUG 标题
- 一句话概括，不超过 30 字
- 格式：「[模块/功能] + [异常关键词]」
- 例：「胖柚甄选加购商品失败」「首页 Banner 点击无响应」

### 2. 操作步骤
- 3~5 步为宜，最多不超过 7 步
- 每步一行，写清关键操作（页面 + 点击/输入的关键元素）
- 不要写「等待系统响应」「页面发生变化」之类的废话
- 不要重复描述显而易见的页面状态

### 3. 实际结果
- 1~2 句话
- 包含关键错误信息（弹窗文案、错误码必须原文照抄）

### 4. 预期结果
- 1~2 句话
- 描述正常情况下应该发生什么

## 输出格式（严格使用以下 Markdown，不要输出其他任何内容）

```
## BUG 标题
[一句话标题]

## 操作步骤
1. [步骤1]
2. [步骤2]
3. [步骤3]

## 实际结果
[1~2 句话描述]

## 预期结果
[1~2 句话描述]
```

## 注意事项
- 商品名、按钮文案、错误提示必须原文照抄，不要意译
- 看不清细节就根据上下文合理推断，不要写「无法判断」
- 宁可步骤少一点，每步信息密度高一点"""


# ========== 工具函数 ==========
def find_mavis_cmd() -> str:
    """定位 mavis 命令的实际路径（Windows 上 .cmd 文件需要绝对路径）"""
    found = shutil.which("mavis")
    if found:
        return found
    candidates = [
        r"C:\Users\Admin\.mavis\bin\mavis.cmd",
        os.path.expanduser(r"~\.mavis\bin\mavis.cmd"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "mavis"


def call_ai_video_understand(video_path: str, prompt: str) -> str:
    """
    调用 matrix MCP 的 matrix_videos_understand 工具分析视频。
    通过临时 JSON 文件传参，避免中文路径在命令行中乱码。
    返回 AI 生成的 description 文本。
    """
    request_body = {
        "video_info": [
            {
                "file": video_path.replace("\\", "/"),
                "prompt": prompt,
            }
        ]
    }

    tmp_dir = tempfile.gettempdir()
    tmp_json = os.path.join(tmp_dir, f"video_to_bug_req_{os.getpid()}_{int(time.time())}.json")

    try:
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(request_body, f, ensure_ascii=False)

        mavis_path = find_mavis_cmd()
        if os.path.isabs(mavis_path) and mavis_path.lower().endswith(".cmd"):
            cmd = ["cmd", "/c", mavis_path, "mcp", "call", MCP_SERVER, MCP_TOOL, "--file", tmp_json]
        else:
            cmd = [mavis_path, "mcp", "call", MCP_SERVER, MCP_TOOL, "--file", tmp_json]

        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"MCP 调用失败（退出码 {result.returncode}）:\n{result.stderr or result.stdout}")

        response = json.loads(result.stdout)
        if response.get("code") != 0:
            raise RuntimeError(f"MCP 返回错误: {response.get('message', 'unknown')}")

        results = response.get("results", [])
        if not results:
            raise RuntimeError("MCP 返回结果为空")

        first = results[0]
        if not first.get("success", False):
            raise RuntimeError(f"视频分析失败: {first.get('error', 'unknown')}")

        description = first.get("description", "").strip()
        if not description:
            raise RuntimeError("AI 返回内容为空")

        return description

    finally:
        try:
            os.remove(tmp_json)
        except OSError:
            pass


def call_ai_with_retry(video_path: str, prompt: str, on_retry=None) -> str:
    """带重试的调用包装。on_retry(attempt, exception) 用于回调提示"""
    last_error = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if on_retry:
                on_retry(attempt, None)
            else:
                print(f"  [{attempt}/{MAX_RETRY}] 正在调用 AI 分析视频...", file=sys.stderr, flush=True)
            return call_ai_video_understand(video_path, prompt)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRY:
                if on_retry:
                    on_retry(attempt, e)
                else:
                    print(f"  [失败] {e}", file=sys.stderr)
                    print(f"  [重试] {RETRY_DELAY} 秒后重试...", file=sys.stderr, flush=True)
                time.sleep(RETRY_DELAY)
            else:
                if on_retry:
                    on_retry(attempt, e)

    raise RuntimeError(f"已重试 {MAX_RETRY} 次仍失败: {last_error}")


def copy_to_clipboard(text: str) -> bool:
    """复制到 Windows 剪贴板（通过临时文件 + PowerShell Set-Clipboard）"""
    tmp_file = None
    try:
        tmp_file = os.path.join(tempfile.gettempdir(), f"video_to_bug_clip_{os.getpid()}_{int(time.time())}.txt")
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(text)

        ps_script = (
            f"$content = [System.IO.File]::ReadAllText('{tmp_file}', "
            f"[System.Text.Encoding]::UTF8); Set-Clipboard -Value $content"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[警告] 复制到剪贴板失败: {e}", file=sys.stderr)
        return False
    finally:
        if tmp_file:
            try:
                os.remove(tmp_file)
            except OSError:
                pass


# ========== 输出解析 ==========
def parse_bug_report(text: str) -> dict:
    """
    解析 AI 返回的 BUG 单 Markdown 文本，提取四部分。
    返回 {"title": str, "steps": str, "actual": str, "expected": str, "raw": str}
    """
    result = {"title": "", "steps": "", "actual": "", "expected": "", "raw": text}

    # 匹配 ## BUG 标题
    m = re.search(r"##\s*BUG\s*标题\s*\n+(.+?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        result["title"] = m.group(1).strip()

    # 匹配 ## 操作步骤
    m = re.search(r"##\s*操作步骤\s*\n+(.+?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        result["steps"] = m.group(1).strip()

    # 匹配 ## 实际结果
    m = re.search(r"##\s*实际结果\s*\n+(.+?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        result["actual"] = m.group(1).strip()

    # 匹配 ## 预期结果
    m = re.search(r"##\s*预期结果\s*\n+(.+?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        result["expected"] = m.group(1).strip()

    return result


def sanitize_filename(name: str, max_len: int = 50) -> str:
    """清洗文件名（去除非法字符和容易引起歧义的符号，截断长度）"""
    # Windows 非法字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    # 去掉方括号和日式引号（这些在文件名中容易和 glob 混淆）
    name = re.sub(r'[\[\]【】「」『』]', '', name)
    # 替换空白为下划线
    name = re.sub(r'\s+', '_', name)
    # 截断
    if len(name) > max_len:
        name = name[:max_len]
    return name.strip('_') or "未命名BUG"


# ========== 文件输入展开 ==========
def expand_video_inputs(input_path: str) -> list:
    """
    展开输入路径为视频文件列表。
    支持：
      - 单个视频文件
      - 目录（递归扫描所有视频）
      - glob 通配符（如 D:\\录屏\\*.mp4）
    """
    # glob 通配符（用户显式用了通配符）
    if any(c in input_path for c in ["*", "?"]):
        matched = []
        # pathlib.glob 风格
        for p in _glob.glob(input_path, recursive=True):
            if os.path.isfile(p) and Path(p).suffix.lower() in VIDEO_EXTENSIONS:
                matched.append(os.path.abspath(p))
        if not matched:
            # 兜底：手动 glob（处理 Windows 路径）
            import re as _re
            pattern = _re.escape(input_path).replace(r"\*", ".*").replace(r"\?", ".")
            base_dir = os.path.dirname(input_path) or "."
            for root, _, files in os.walk(base_dir):
                for f in files:
                    if _re.match(pattern, os.path.join(root, f)):
                        if Path(f).suffix.lower() in VIDEO_EXTENSIONS:
                            matched.append(os.path.abspath(os.path.join(root, f)))
        return sorted(set(matched))

    path = os.path.abspath(input_path)
    if os.path.isfile(path):
        return [path]
    elif os.path.isdir(path):
        # 递归扫描目录
        videos = []
        for root, _, files in os.walk(path):
            for f in files:
                if Path(f).suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(os.path.abspath(os.path.join(root, f)))
        return sorted(videos)
    else:
        return []


# ========== 文件保存 ==========
def save_bug_report(bug: dict, video_path: str, output_dir: str, timestamp: str) -> str:
    """保存单个 BUG 单到 .md 文件，文件名用 BUG 标题"""
    os.makedirs(output_dir, exist_ok=True)

    # 文件名：BUG_{清洗后的标题}_{时间戳}.md
    title = bug.get("title") or Path(video_path).stem
    safe_title = sanitize_filename(title)
    out_file = os.path.join(output_dir, f"BUG_{safe_title}_{timestamp}.md")

    # 避免文件名冲突
    counter = 1
    while os.path.exists(out_file):
        out_file = os.path.join(output_dir, f"BUG_{safe_title}_{timestamp}_{counter}.md")
        counter += 1

    video_name = Path(video_path).name
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# {bug.get('title') or 'BUG 单'}\n\n")
        f.write(f"> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"> 视频文件: `{video_path}`\n\n")
        f.write("---\n\n")
        f.write(bug["raw"])
        f.write("\n")

    return out_file


def save_batch_report(bugs: list, output_dir: str) -> str:
    """保存批量处理汇总报告"""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(output_dir, f"批量BUG汇总_{timestamp}.md")

    success = [b for b in bugs if b["report"] is not None]
    failed = [b for b in bugs if b["report"] is None]

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# video_to_bug 批量处理汇总\n\n")
        f.write(f"> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"> 总数: {len(bugs)} | 成功: {len(success)} | 失败: {len(failed)}\n\n")
        f.write("---\n\n")

        if failed:
            f.write("## 处理失败\n\n")
            for b in failed:
                f.write(f"- `{Path(b['video']).name}`: {b['error']}\n")
            f.write("\n---\n\n")

        f.write("## BUG 列表\n\n")
        for i, b in enumerate(success, 1):
            r = b["report"]
            f.write(f"### {i}. {r['title'] or Path(b['video']).stem}\n\n")
            f.write(f"**视频文件**: `{b['video']}`\n\n")
            f.write("**操作步骤**:\n")
            f.write(r["steps"] + "\n\n")
            f.write("**实际结果**: " + r["actual"] + "\n\n")
            f.write("**预期结果**: " + r["expected"] + "\n\n")
            f.write("---\n\n")

    return out_file


# ========== 单个视频处理 ==========
def process_single_video(video_path: str) -> dict:
    """
    处理单个视频，返回结果字典：
    {
        "video": str,
        "report": dict | None,  # parse_bug_report 的结果
        "raw": str,             # AI 原始输出
        "error": str | None,
    }
    """
    try:
        raw = call_ai_with_retry(video_path, PROMPT_TEMPLATE)
        report = parse_bug_report(raw)
        return {"video": video_path, "report": report, "raw": raw, "error": None}
    except Exception as e:
        return {"video": video_path, "report": None, "raw": "", "error": str(e)}


# ========== 终端输出格式化 ==========
def format_bug_for_print(bug: dict, index: int = None) -> str:
    """格式化单个 BUG 单输出到控制台"""
    r = bug["report"]
    header = "=" * 60
    title_prefix = f"#{index} " if index is not None else ""
    return (
        f"\n{header}\n"
        f"{title_prefix}BUG 标题: {r['title'] or '(未提取到)'}\n"
        f"视频: {bug['video']}\n"
        f"{header}\n"
        f"{bug['raw']}\n"
    )


# ========== Main ==========
def main():
    parser = argparse.ArgumentParser(
        description="录屏视频一键转 BUG 单工具（v2）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单个视频
  python video_to_bug.py "D:\\录屏\\加购失败.mp4" --save

  # 批量处理（整个目录）
  python video_to_bug.py "D:\\录屏\\" --save
  python video_to_bug.py "D:\\录屏\\*.mp4" --save

  # 自定义输出目录
  python video_to_bug.py "D:\\录屏\\" --save --output-dir "D:\\BUG单"
        """,
    )
    parser.add_argument("input", help="视频文件、目录或通配符（mp4/mov/avi/mkv 等）")
    parser.add_argument("--save", action="store_true", help="保存到 .md 文件")
    parser.add_argument("--output-dir", default=None, help="保存目录（默认工具目录下 output/）")
    parser.add_argument("--no-clipboard", action="store_true", help="不自动复制到剪贴板")
    parser.add_argument(
        "--clipboard-each", action="store_true",
        help="批量模式时每个视频单独复制到剪贴板（默认只复制最后一个）",
    )

    args = parser.parse_args()

    # 展开输入
    videos = expand_video_inputs(args.input)
    if not videos:
        print(f"[错误] 未找到视频文件: {args.input}", file=sys.stderr)
        sys.exit(1)

    is_batch = len(videos) > 1
    print(f"[扫描] 找到 {len(videos)} 个视频文件{'（批量模式）' if is_batch else ''}", file=sys.stderr)

    # 处理所有视频
    results = []
    for i, vp in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] 处理: {Path(vp).name}", file=sys.stderr)
        result = process_single_video(vp)
        results.append(result)

        if result["error"]:
            print(f"  [失败] {result['error']}", file=sys.stderr)
        else:
            r = result["report"]
            print(f"  [OK] 标题: {r['title'] or '(空)'}", file=sys.stderr)

    # 输出到控制台
    print("\n" + "=" * 60, file=sys.stderr)
    print("生成的 BUG 单：", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)

    success_results = [r for r in results if r["report"]]
    for i, r in enumerate(success_results, 1):
        print(format_bug_for_print(r, index=i))

    # 复制到剪贴板
    if not args.no_clipboard and success_results:
        if is_batch and not args.clipboard_each:
            # 批量模式：复制汇总
            combined = "\n\n".join(
                format_bug_for_print(r, index=i)
                for i, r in enumerate(success_results, 1)
            )
            if copy_to_clipboard(combined):
                print(f"\n[OK] 已复制 {len(success_results)} 个 BUG 单到剪贴板", file=sys.stderr)
        else:
            # 单个/每个单独复制：复制最后一个成功的
            last = success_results[-1]
            if copy_to_clipboard(last["raw"]):
                print(f"\n[OK] 已复制最新一个 BUG 单到剪贴板（Ctrl+V 提交）", file=sys.stderr)

    # 保存到文件
    if args.save:
        output_dir = args.output_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "output"
        )
        os.makedirs(output_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        for r in success_results:
            out = save_bug_report(r["report"], r["video"], output_dir, timestamp)
            print(f"  [已保存] {out}", file=sys.stderr)

        # 批量模式额外生成汇总报告
        if is_batch:
            summary = save_batch_report(results, output_dir)
            print(f"  [汇总] {summary}", file=sys.stderr)

    print(f"\n[完成] 共 {len(results)} 个，成功 {len(success_results)}，失败 {len(results) - len(success_results)}", file=sys.stderr)


if __name__ == "__main__":
    main()
