# VMA/VMR - Video Metrics Analyzer & Reporter



---

# Part 1: VMA (Backend) - Video Metrics Analyzer

## 核心架构

### 双服务设计
```
FastAPI (8078)          Streamlit (8081)
    ↓                         ↓
任务管理/执行              报告可视化
    ↓                         ↓
生成 JSON 数据           读取 JSON + 渲染
```

### 三大功能模块

| 模块 | JobMode | 处理器 | 输出文件 | 用途 |
|------|---------|--------|----------|------|
| Stream Analysis | `bitstream_analysis` | `stream_analysis_runner.py` | `stream_analysis.json` | 分析已有编码视频的质量 |
| Metrics Analysis | `metrics_analysis` | `metrics_analysis_runner.py` | `metrics_analysis.json` | 批量编码源视频+质量分析 |
| Metrics Comparison | `metrics_comparison` | `metrics_comparison_runner.py` | `metrics_comparison.json` | Anchor vs Test 对比分析 |

---

## 关键数据结构（重要！）

### ⚠️ 数据结构统一性要求

**用户明确要求**：所有 Metrics 类型的报告必须使用相同的数据结构，便于代码复用。

#### Stream Analysis 数据结构（有 metrics 包装器）

```json
{
  "kind": "bitstream_analysis",
  "reference": {...},
  "encoded": [
    {
      "label": "encoded_crf23.h265",
      "width": 1280, "height": 720, "fps": 30,
      "metrics": {                              // ← 注意这个包装器
        "psnr": {
          "summary": {"psnr_avg": 42.5, ...},  // ← 注意 summary 子键
          "frames": [...]
        },
        "ssim": {
          "summary": {"ssim_avg": 0.98, ...},
          "frames": [...]
        },
        "vmaf": {
          "summary": {"vmaf_mean": 95.2, ...},
          "frames": [...]
        }
      },
      "bitrate": {"avg_bitrate_bps": 2500000, ...}
    }
  ]
}
```

**解析方式**（在 `4_📈_Stream_Comparison.py`）:
```python
metrics = item.get("metrics", {}) or {}
psnr = (metrics.get("psnr", {}) or {}).get("summary", {}) or {}
value = psnr.get("psnr_avg")
```

#### Metrics 数据结构（无 metrics 包装器！）

```json
{
  "kind": "metrics_analysis_single",           // Metrics Analysis
  // 或 "template_metrics"                       // Metrics Comparison
  "entries": [
    {
      "source": "video1.mp4",
      "encoded": [
        {
          "label": "video1_crf23.h264",
          "avg_bitrate_bps": 2500000,
          "psnr": {                              // ← 直接在 encoded 里，无包装器！
            "psnr_avg": 42.5,
            "psnr_y": 40.2,
            "psnr_u": 44.1,
            "psnr_v": 43.8
          },
          "ssim": {                              // ← 直接在 encoded 里
            "ssim_avg": 0.98,
            "ssim_y": 0.97,
            ...
          },
          "vmaf": {                              // ← 直接在 encoded 里
            "vmaf_mean": 95.2,
            "vmaf_neg_mean": 94.8
          },
          "performance": {                       // ← 性能数据直接在 encoded 里
            "encoding_fps": 120.5,
            "cpu_avg_percent": 45.2,
            ...
          }
        }
      ]
    }
  ]
}
```

**解析方式**（在 `2_📊_Metrics_Details.py` 和 `3_🆚_Metrics_Comparison.py`）:
```python
metrics = item                                 # ← 注意：直接是 item，不是 item["metrics"]
value = metrics.get("psnr", {}).get("psnr_avg")
```

### ⚠️ 易错点：数据结构不匹配

**错误案例**：
```python
# ❌ 错误：Metrics 数据结构中这样解析会失败
metrics = item.get("metrics") or {}
value = metrics.get("psnr", {}).get("psnr_avg")  # 返回 None
```

**正确做法**：
```python
# ✅ 正确：Metrics 数据结构直接使用 item
metrics = item
value = metrics.get("psnr", {}).get("psnr_avg")
```

**为什么会混淆？**
- `build_bitstream_report()` 返回两个值：`(report_data, summary)`
- `report_data`（第一个返回值）：有 `metrics` 包装器 → 用于 Stream Analysis
- `summary`（第二个返回值）：**无** `metrics` 包装器 → 用于 Metrics Analysis/Comparison

**代码位置**：`src/services/stream_analysis_runner.py:270-290`

---

## 性能数据采集

### 设计原则

**用户要求**：复用现有代码，避免重复实现。

### 核心模块

**文件**：`src/utils/performance.py`

**数据结构**：
```python
@dataclass
class PerformanceData:
    encoding_fps: Optional[float] = None
    total_encoding_time_s: Optional[float] = None
    total_frames: Optional[int] = None
    cpu_avg_percent: Optional[float] = None
    cpu_max_percent: Optional[float] = None
    cpu_samples: List[float] = field(default_factory=list)
```

**使用方式**：
```python
from src.utils.performance import run_encode_with_perf

returncode, stdout, stderr, perf = await run_encode_with_perf(cmd, encoder_type)
# perf: PerformanceData 对象
perf_dict = perf.to_dict()  # 转换为字典，过滤 None 值
```

### ⚠️ 易错点：复用已有码流时的性能数据

**场景**：Anchor 码流已存在，跳过编码

**错误做法**：
```python
# ❌ 错误：添加空的 PerformanceData()
if skip_encode and out_path.exists():
    file_outputs.append(out_path)
    file_perfs.append(PerformanceData())  # 全是 None，但仍是对象
```

**问题**：
```python
# 添加到 encoded 时
if perf_dict:  # ← 空对象的 to_dict() 返回 {}，truthy 为 True
    enc_item["performance"] = {}  # ← 添加了空的 performance 字段
```

**正确做法**：
```python
# ✅ 正确：添加 None 标记无数据
if skip_encode and out_path.exists():
    file_outputs.append(out_path)
    file_perfs.append(None)  # ← 用 None 标记
```

```python
# 添加到 encoded 时
perf = perf_list[i]
if perf is not None:  # ← 检查 None
    enc_item["performance"] = perf.to_dict()
```

**代码位置**：
- `src/services/metrics_comparison_runner.py:203-211`（Metrics Comparison）
- `src/services/metrics_analysis_runner.py:72-77`（Metrics Analysis）

---

## 视频处理逻辑

### 编码阶段：分辨率和帧率转换

**命令构建**：`src/utils/encoding.py:build_encode_cmd()`

**FFmpeg 滤镜**：
```bash
ffmpeg -i input.mp4 \
  -vf "fps=30,scale=1280:720:flags=bicubic" \
  -c:v libx264 -crf 23 output.h264
```

**参数说明**：
- `shortest_size`: 根据最短边计算分辨率（保持宽高比）
- `target_fps`: 目标帧率
- 缩放算法：bicubic

### 打分阶段：管道方式（不保存临时 YUV）

**命令构建**：`src/services/ffmpeg.py:calculate_metrics_pipeline()`

**Shell 管道**：
```bash
(ffmpeg -i encoded.h264 -vf "scale=1920:1080,format=yuv420p" -f rawvideo -) | \
(ffmpeg -i source.mp4 -vf "fps=30,format=yuv420p" -f rawvideo -) | \
ffmpeg -f rawvideo -s 1920x1080 -r 30 -i pipe:3 \
       -f rawvideo -s 1920x1080 -r 30 -i pipe:4 \
       -filter_complex "libvmaf=..." -f null -
```

**Metrics 策略**：
- `upscale_to_source=True`：码流上采样到源分辨率（默认）
- `upscale_to_source=False`：源视频下采样到码流分辨率

### 指标解析

**文件**：`src/utils/metrics.py`

**关键函数**：
```python
# 解析 summary（用于 Metrics 类型）
parse_psnr_summary(log_content) → {"psnr_avg": ..., "psnr_y": ...}
parse_ssim_summary(log_content) → {"ssim_avg": ..., "ssim_y": ...}
parse_vmaf_summary(log_content) → {"vmaf_mean": ..., "vmaf_neg_mean": ...}

# 解析 full（用于 Stream Analysis）
parse_psnr_log(log_content) → {"summary": {...}, "frames": [...]}
parse_ssim_log(log_content) → {"summary": {...}, "frames": [...]}
parse_vmaf_log(log_content) → {"summary": {...}, "frames": [...]}
```

⚠️ **重要**：
- **必须使用 `parse_*_summary` 用于 Metrics 类型**（保证数据结构统一）
- **使用 `parse_*_log` 用于 Stream Analysis**（需要 frames 数据）

**代码位置**：`src/services/ffmpeg.py:633-679`

---

## BD-Rate 计算

**文件**：`src/utils/bd_rate.py`

**函数**：
```python
bd_rate(r1, m1, r2, m2) → float  # BD-Rate（百分比）
bd_metrics(r1, m1, r2, m2) → float  # BD-Metrics（绝对值）
```

**参数**：
- `r1`: Anchor 码率列表
- `m1`: Anchor 指标列表（PSNR/SSIM/VMAF）
- `r2`: Test 码率列表
- `m2`: Test 指标列表

**要求**：至少 4 个码率点

---

## API 端点

### 任务 API (`src/api/jobs.py`)
- `POST /api/jobs` - 创建 Stream Analysis 任务
- `GET /api/jobs` - 列出所有任务
- `GET /api/jobs/{job_id}` - 获取任务详情
- `DELETE /api/jobs/{job_id}` - 删除任务

### Metrics Analysis API (`src/api/metrics_analysis.py`)
- `POST /api/metrics-analysis/templates` - 创建 Metrics Analysis 模板
- `GET /api/metrics-analysis/templates` - 列出模板
- `POST /api/metrics-analysis/templates/{template_id}/jobs` - 创建任务

### Metrics Comparison API (`src/api/templates.py`)
- `POST /api/templates` - 创建 Metrics Comparison 模板
- `GET /api/templates` - 列出模板
- `PUT /api/templates/{template_id}` - 更新模板
- `DELETE /api/templates/{template_id}` - 删除模板
- `POST /api/templates/{template_id}/jobs` - 创建任务

---

## 关键文件速查

| 文件 | 用途 | 关键点 |
|------|------|--------|
| `src/services/ffmpeg.py` | FFmpeg 封装 | 编码、指标计算、管道打分 |
| `src/services/stream_analysis_runner.py` | Stream Analysis 执行器 | 返回两个值：(report, summary) |
| `src/services/metrics_comparison_runner.py` | Metrics Comparison 执行器 | 使用共享性能模块，复用码流时添加 None |
| `src/services/metrics_analysis_runner.py` | Metrics Analysis 执行器 | 使用 summary，保证数据结构统一 |
| `src/utils/performance.py` | 性能监控共享模块 | CPU 采样、FPS 计算、编码时间 |
| `src/utils/encoding.py` | 编码命令构建 | 分辨率/帧率转换滤镜 |
| `src/utils/bd_rate.py` | BD-Rate 计算 | 需要至少 4 个码率点 |
| `src/utils/streamlit_helpers.py` | Streamlit 辅助函数 | `_metric_value()` 直接访问字段 |

---

# Part 2: VMR (Frontend) - Video Metrics Reporter

## 页面路由

```
1_🏠_Home.py (首页)
    ├─→ 2_📊_Metrics_Details.py (Metrics 详情报告)
    ├─→ 3_🆚_Metrics_Comparison.py (Metrics 对比报告)
    └─→ 4_📈_Stream_Comparison.py (Stream 分析报告)
```

**URL 跳转规则**：
- Metrics Details: `/Metrics_Details?job_id={job_id}`
- Metrics Comparison (任务对比): `/Metrics_Comparison?anchor_job={id1}&test_job={id2}`
- Metrics Comparison (模板报告): `/Metrics_Comparison?template_job_id={job_id}`
- Stream Comparison: `/Stream_Comparison?job_id={job_id}`

⚠️ **注意**：首页链接使用 `/Stream_Comparison`，不是 `/Stream_Analysis`

---

## 报告类型详解

### 1. Metrics 详情报告（单个 Metrics Analysis 任务）

**页面**：`2_📊_Metrics_Details.py`

**访问方式**：
- 从首页点击"最近的Metrics详情报告"
- 直接 URL: `/Metrics_Details?job_id={job_id}`

**数据源**：`data/jobs/{job_id}/metrics_analysis/metrics_analysis.json`

**报告结构**：
1. **Information** - 编码配置信息
2. **Overall** - 整体指标汇总
3. **Metrics** - RD 曲线
4. **Details** - 详细指标表格
5. **Performance** - 编码性能数据（如果有）
6. **Machine Info** - 执行环境信息

**数据解析关键**：
```python
# ✅ 正确：metrics 直接是 item
for item in entry.get("encoded") or []:
    metrics = item  # ← 不是 item.get("metrics")
    psnr = metrics.get("psnr", {}).get("psnr_avg")
```

**代码位置**：`src/pages/2_📊_Metrics_Details.py:48`

---

### 2. 基于任务的 Metrics 对比报告

**页面**：`3_🆚_Metrics_Comparison.py`（模式1）

**访问方式**：
- 从首页选择两个 Metrics Analysis 任务后生成
- 直接 URL: `/Metrics_Comparison?anchor_job={id1}&test_job={id2}`

**数据源**：
- Anchor: `data/jobs/{anchor_job}/metrics_analysis/metrics_analysis.json`
- Test: `data/jobs/{test_job}/metrics_analysis/metrics_analysis.json`

**报告结构**（与模板报告完全一致）：
1. **Information** - 编码器配置对比
2. **Overall** - 整体指标汇总 + BD-Rate 汇总
3. **Metrics** - RD 曲线 + Delta 分析 + Details
4. **BD-Rate** - BD-Rate 汇总表 + 4 个独立柱状图
5. **BD-Metrics** - BD-Metrics 汇总表 + 4 个独立柱状图
6. **Performance** - 性能对比（FPS、CPU）
7. **Machine Info** - Anchor 和 Test 环境信息

**侧边栏**：完整的章节导航

**数据解析关键**：
```python
# ✅ 正确：metrics 直接是 item
for item in entry.get("encoded") or []:
    metrics = item  # ← 不是 item.get("metrics")
    psnr = metrics.get("psnr", {}).get("psnr_avg")
```

**代码位置**：`src/pages/3_🆚_Metrics_Comparison.py:62-63`

---

### 3. 基于模板的 Metrics 对比报告

**页面**：`3_🆚_Metrics_Comparison.py`（模式2）

**访问方式**：
- 从首页点击"模板对比报告"
- 直接 URL: `/Metrics_Comparison?template_job_id={job_id}`

**数据源**：`data/jobs/{job_id}/metrics_analysis/metrics_comparison.json`

**报告结构**：与任务对比报告**完全一致**

**额外功能**：码率对比图表
- 选择视频和码率点
- 柱状图/折线图显示 Anchor vs Test 码率变化
- 可调聚合间隔

**数据解析关键**：
```python
# ✅ 正确：metrics 直接是 item
for item in side.get("encoded") or []:
    metrics = item  # ← 不是 item.get("metrics")
    psnr = metrics.get("psnr", {}).get("psnr_avg")
```

**代码位置**：`src/pages/3_🆚_Metrics_Comparison.py:370-386`

---

### 4. Stream 分析报告

**页面**：`4_📈_Stream_Comparison.py`

**访问方式**：
- 从首页点击"最近的Stream分析报告"
- 直接 URL: `/Stream_Comparison?job_id={job_id}`

**数据源**：`data/jobs/{job_id}/analysis/stream_analysis.json`

**报告结构**：
1. **Reference Info** - 参考视频信息
2. **Encoded Videos** - 编码视频列表和指标
3. **Frame-Level Metrics** - 逐帧 PSNR/SSIM/VMAF 曲线
4. **Bitrate Analysis** - 帧类型分布、码率分析

**数据解析关键**：
```python
# ✅ 正确：Stream 有 metrics 包装器，且有 summary 子键
for item in encoded_items:
    metrics = item.get("metrics", {}) or {}
    psnr = (metrics.get("psnr", {}) or {}).get("summary", {}) or {}
    value = psnr.get("psnr_avg")
```

**代码位置**：`src/pages/4_📈_Stream_Comparison.py:228-234`

---

## 统一解析函数

**文件**：`src/utils/streamlit_helpers.py`

```python
def _metric_value(metrics: Dict[str, Any], name: str, field: str) -> Optional[float]:
    """从 metrics 字典中提取指标值"""
    block = metrics.get(name) or {}
    if not isinstance(block, dict):
        return None
    return block.get(field)
```

**使用方式**：
```python
# Metrics 类型（无 metrics 包装器）
metrics = item  # 直接是 item
psnr = _metric_value(metrics, "psnr", "psnr_avg")

# Stream 类型（有 metrics 包装器）
metrics = item.get("metrics", {}) or {}
psnr = _metric_value(metrics, "psnr", "psnr_avg")
```

---

## 通用组件库

**文件**：`src/utils/streamlit_metrics_components.py`

**组件列表**：
- `inject_smooth_scroll_css()` - 平滑滚动
- `render_sidebar_contents_single()` - 单报告侧边栏
- `render_sidebar_contents()` - 对比报告侧边栏
- `render_overall_section()` - Overall 汇总
- `render_rd_curves()` - RD 曲线
- `render_metrics_delta()` - Delta 分析
- `render_performance_section()` - 性能分析
- `render_bd_rate_section()` - BD-Rate 分析
- `render_bd_metrics_section()` - BD-Metrics 分析
- `render_machine_info()` - 机器信息

**设计原则**：
- 组件可复用于不同报告页面
- 统一视觉风格
- 统一交互体验

---

## ⚠️ 易错点总结

### 1. 数据结构混淆
| 报告类型 | 数据结构 | 解析方式 |
|---------|---------|---------|
| Stream Analysis | `encoded[i].metrics.pnr.summary.psnr_avg` | `item.get("metrics").get("psnr").get("summary")` |
| Metrics Analysis | `encoded[i].psnr.psnr_avg` | `item` 直接 |
| Metrics Comparison | `encoded[i].psnr.psnr_avg` | `item` 直接 |

### 2. 页面路由错误
- ❌ 错误：`/Stream_Analysis`
- ✅ 正确：`/Stream_Comparison`

### 3. 性能数据采集
- 复用已有码流时：添加 `None`，不要添加 `PerformanceData()`
- 添加到 encoded 时：检查 `if perf is not None`

### 4. 指标解析函数选择
- Metrics 类型：使用 `parse_*_summary`
- Stream 类型：使用 `parse_*_log`

---

## 用户明确要求

1. **数据结构统一**：所有 Metrics 类型报告使用相同数据结构（无 metrics 包装器）
2. **代码复用**：性能监控、BD-Rate 计算、指标解析等功能模块化
3. **报告结构一致**：任务对比报告和模板对比报告结构完全相同
4. **交互体验**：侧边栏导航、平滑滚动、统一视觉风格
