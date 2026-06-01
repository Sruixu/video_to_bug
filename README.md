# video_to_bug - 录屏视频一键转 BUG 单

把录制的 BUG 复现视频扔进去，AI 自动拆出**BUG 标题 / 操作步骤 / 实际结果 / 预期结果**四段，复制到剪贴板，直接 Ctrl+V 提交 BUG 单。

**走 mavis MCP**，本机零额外配置，开箱即用。

支持**单文件**、**批量处理**、**GUI 界面**三种使用方式。

---

## 快速开始（3 步）

```powershell
# 1. 装依赖（一次性）
pip install imageio-ffmpeg imageio

# 2. 确认本机 mavis MCP 服务已就绪
mavis --version
mavis mcp ls   # 应该看到 matrix 服务，状态 authenticated

# 3. 启动 GUI
D:\sruixu\video2bug\video_to_bug_gui.bat
# 或命令行
python D:\sruixu\video2bug\video_to_bug_gui.py
```

**GUI 使用**：
1. 点「选择文件」选视频
2. 点「▶ 开始处理」
3. 右侧 BUG 单出来了，点「复制全部」Ctrl+V 提交

---

## 工作原理

工具调用本机 `mavis` CLI → `matrix` MCP 服务的 `videos_understand` 工具分析视频，AI 看完整段录屏后输出结构化 BUG 单。

**前置条件**：
- 本机已装 `mavis` CLI
- `mavis` 已配置 `matrix` MCP 服务
- Python 3.10+
- 已 `pip install imageio-ffmpeg imageio`

**为什么走 MCP**：
- ✅ **零额外配置** — 复用本机 mavis 服务
- ✅ **零外部成本** — 用你自己的 mavis/MiniMax 额度
- ✅ **视频分析精度高** — matrix MCP 视频理解能力比通用视觉模型强
- ✅ **完全离线运行** — 工具代码里没有任何外部密钥、token、账号

---

## mavis MCP 配置

### 检查 mavis 是否已配好

```powershell
mavis --version
# 应该输出 3.0+

mavis mcp ls
# 应该看到 matrix 服务，状态 authenticated
```

### 没装 matrix MCP？

```powershell
mavis mcp add matrix npx -y @MiniMax/matrix-mcp
mavis mcp ls   # 验证装好了
```

如果你的 mavis 是 MiniMax 官方版本，**matrix MCP 一般默认装好**，直接用就行。

---

## 两种使用方式

### 1. GUI（推荐）

```powershell
D:\sruixu\video2bug\video_to_bug_gui.bat
```

界面布局：
- 顶部蓝色标题栏
- 左栏：MCP 提示 → 待处理视频 → 处理选项 → 进度+按钮
- 右栏：BUG 单预览

### 2. 命令行（高级）

```powershell
cd D:\sruixu\video2bug

# 单个视频
python video_to_bug.py "D:\录屏\加购失败.mp4" --save

# 批量：目录
python video_to_bug.py "D:\录屏\" --save

# 批量：通配符
python video_to_bug.py "D:\录屏\*.mp4" --save
```

---

## 安装

### Python 3.10+

官网下载安装：https://www.python.org/downloads/（勾选 Add to PATH）

### imageio-ffmpeg（带 ffmpeg）

```powershell
pip install imageio-ffmpeg imageio
```

这个包**自带 ffmpeg 静态二进制**（约 80MB），**不用手动装系统 ffmpeg，也不用配 PATH**。

### mavis CLI + matrix MCP

一般是 MiniMax 用户的标配。如果没有，参考 [mavis 官方文档](https://github.com/MiniMax/mavis) 安装。

---

## 故障排查

| 报错 | 原因 | 解决 |
|---|---|---|
| `mavis: command not found` | mavis CLI 不在 PATH | 装 mavis 或加 `C:\Users\<你>\.mavis\bin` 到 PATH |
| `tool "videos_understand" not found` | matrix MCP 未注册 | `mavis mcp ls` 检查；没装就 `mavis mcp add matrix ...` |
| `视频分析失败: ...` | matrix MCP 调用出错 | 看错误信息；可能是网络问题或临时服务不可用 |
| 跑出来后 AI 输出奇怪 | 模型对 UI 视频理解能力有限 | 重试一次，或检查视频质量 |
| 窗口看不到「开始处理」按钮 | 窗口太小 | 拉大窗口高度（最小 720px） |
| 中文显示成方块 | 缺中文字体 | 装 Microsoft YaHei 等中文字体 |

---

## 文件结构

```
D:\sruixu\video2bug\
├── video_to_bug_gui.bat   # GUI 启动器（双击这个）
├── video_to_bug_gui.py    # GUI 界面（蓝色主题）
├── video_to_bug.py        # 命令行脚本（高级/批量用）
├── README.md              # 本文档
├── .gitignore             # 防误提交
└── output\                # 默认输出目录（首次跑后自动创建）
```

极简 — 2 个核心脚本 + 1 个启动器，1 个 Python 依赖包。

---

## 输出示例

```markdown
## BUG 标题
[xxxx] 购物车删除商品后，首页商品加购数量未同步重置

## 操作步骤
1. 首页胖柚甄选列表加入「可乐」到购物车
2. 进入购物车删除该商品
3. 返回首页

## 实际结果
首页该商品「+」号处仍显示数量 1，未重置为 0

## 预期结果
购物车删除后，首页对应商品数量应同步重置为 0
```

文件名格式：`BUG_<标题>_<时间戳>.md`

---

