# VMA - Video Metrics Analyzer

## 项目架构

```
VMA/
├── src/
│   ├── main.py                 # FastAPI VMA 应用入口
│   ├── config.py               # 配置管理（从 config.yml 加载）
│   ├── 1_🏠_Home.py        # Streamlit VMR 报告首页
│   ├── api/                    # FastAPI 路由
│   │   ├── jobs.py             # 任务 API（创建/查询/删除任务）
│   │   ├── templates.py        # Metrics Comparison 模板 API
│   │   ├── metrics_analysis.py # Metrics Analysis 模板 API
│   │   └── pages.py            # 页面路由（模板管理、任务详情）
│   ├── models/
│   │   ├── job.py              # 任务数据模型（Job, JobMetadata, JobStatus）
│   │   └── template.py         # 模板数据模型（EncodingTemplate, TemplateSideConfig）
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/
│   │   ├── storage.py          # 任务存储服务（JobStorage）
│   │   ├── template_storage.py # 模板存储服务
│   │   ├── processor.py        # 后台任务处理器（Stream Analysis）
│   │   ├── ffmpeg.py           # FFmpeg 服务（编码、指标计算）
│   │   ├── bitstream_analysis.py # 码流分析服务
│   │   ├── template_runner.py  # Metrics Comparison 执行器
│   │   └── metrics_analysis_runner.py # Metrics Analysis 执行器
│   ├── utils/
│   │   ├── encoding.py         # 编码工具（构建编码命令）
│   │   ├── video_processing.py # 视频处理工具（分辨率/帧率转换）
│   │   ├── metrics.py          # 指标解析工具
│   │   ├── bd_rate.py          # BD-Rate 计算
│   │   └── streamlit_*.py      # Streamlit 辅助工具
│   ├── pages/                  # Streamlit 报告页面
│   │   ├── 2_📊_Metrics_Analysis.py
│   │   ├── 3_🆚_Metrics_Comparison.py
│   │   └── 4_📈_Stream_Analysis.py
│   └── templates/              # Jinja2 HTML 模板（FastAPI Web UI）
├── config.yml                  # 配置文件
└── run.sh                      # 启动脚本
```

## 双服务架构

VMA 由两个服务组成：

1. **FastAPI VMA 服务** (默认端口 8078)
   - 提供 REST API 和 Web UI
   - 管理任务和模板
   - 后台任务处理器

2. **Streamlit VMR 服务** (默认端口 8079)
   - 报告可视化系统
   - 交互式图表展示
   - 支持 PSNR/SSIM/VMAF 曲线、BD-Rate 等

## 三大功能模块

### 1. Stream Analysis（码流分析）

**用途**：分析单个或多个编码视频相对于参考视频的质量指标。

**流程**：
1. 用户上传参考视频（YUV、裸流或容器格式）和编码视频
2. 系统自动检测视频格式（h264/h265/容器）
3. 计算 PSNR、SSIM、VMAF及码率分析。
4. 生成分析报告。

**任务模式**：`JobMode.BITSTREAM_ANALYSIS`

**处理器**：`src/services/processor.py` → `bitstream_analysis.py`

**报告内容**：
- 参考视频信息（分辨率、帧率、帧数）
- 每个编码视频的指标（PSNR/SSIM/VMAF 均值和逐帧数据）
- 码率分析（平均码率、帧类型分布、帧大小）

### 2. Metrics Analysis（指标分析）

**用途**：使用模板配置批量编码源视频并计算质量指标。

**流程**：
1. 创建 Metrics Analysis 模板，配置：
   - 源视频目录
   - 编码器类型和参数
   - 码率控制（CRF/ABR）和码率点位
   - 视频处理参数（shortest_size、target_fps、upscale_to_source）
2. 创建任务执行模板
3. 系统自动编码所有源视频的所有码率点
4. 计算每个编码视频的质量指标

**任务模式**：`JobMode.METRICS_ANALYSIS`

**处理器**：`src/services/metrics_analysis_runner.py`

**模板类型**：`TemplateType.METRICS_ANALYSIS`

### 3. Metrics Comparison（指标对比）

**用途**：对比两组编码配置（Anchor vs Test）的质量指标，计算 BD-Rate。

**流程**：
1. 创建 Metrics Comparison 模板，配置 Anchor 和 Test 两侧：
   - 共用源视频目录
   - 各自的编码器配置和码流目录
   - 码率点位（两侧必须一致）
2. 创建任务执行模板
3. 系统编码两侧的所有视频
4. 计算质量指标并生成 BD-Rate 对比

**任务模式**：`JobMode.METRICS_COMPARISON`

**处理器**：`src/services/template_runner.py`

**模板类型**：`TemplateType.METRICS_COMPARISON`

**报告内容**：
- Anchor 和 Test 的编码配置
- 每个源视频的指标对比
- BD-Rate（PSNR/SSIM/VMAF/VMAF-NEG）
- 编码性能数据（FPS、CPU 占用）
- 环境信息（OS、CPU、内存）

## 数据模型

### Job（任务）

```python
class JobMetadata:
    job_id: str              # 任务 ID（nanoid 12字符）
    status: JobStatus        # pending/processing/completed/failed
    mode: JobMode            # bitstream_analysis/metrics_analysis/metrics_comparison
    template_id: str         # 关联的模板 ID
    command_logs: List[CommandLog]  # 命令执行记录
    execution_result: dict   # 执行结果
```

### Template（模板）

```python
class TemplateSideConfig:
    skip_encode: bool        # 跳过编码（使用已有码流）
    source_dir: str          # 源视频目录
    encoder_type: EncoderType  # ffmpeg/x264/x265/vvenc
    encoder_params: str      # 编码参数
    rate_control: RateControl  # crf/abr
    bitrate_points: List[float]  # 码率点位
    bitstream_dir: str       # 码流输出目录
    shortest_size: int       # 最短边尺寸（可选）
    target_fps: float        # 目标帧率（可选）
    upscale_to_source: bool  # Metrics 策略（默认 True）
    concurrency: int         # 并发数量

class EncodingTemplateMetadata:
    template_id: str
    name: str
    template_type: TemplateType  # metrics_analysis/metrics_comparison
    anchor: TemplateSideConfig
    test: TemplateSideConfig     # 仅 metrics_comparison
```

## 视频处理逻辑

### 编码阶段

使用 `-vf` 滤镜进行帧率和分辨率转换：

```bash
ffmpeg -i input.mp4 -vf "fps=30,scale=1280:720:flags=bicubic" -c:v libx265 -crf 23 output.h265
```

- `shortest_size`：根据最短边计算目标分辨率（保持宽高比）
- `target_fps`：目标帧率转换
- 缩放算法：bicubic

### 打分阶段（管道方式）

不保存临时 YUV 文件，通过 shell 管道连接多个 ffmpeg 进程：

```bash
(ffmpeg -i encoded.h265 -vf "scale=1920:1080,format=yuv420p" -f rawvideo -) | \
(ffmpeg -i source.mp4 -vf "fps=30,format=yuv420p" -f rawvideo -) | \
ffmpeg -f rawvideo -s 1920x1080 -r 30 -i pipe:3 -f rawvideo -s 1920x1080 -r 30 -i pipe:4 \
  -filter_complex "libvmaf=..." -f null -
```

**Metrics 策略**：
- `upscale_to_source=True`：码流上采样到源分辨率（默认）
- `upscale_to_source=False`：源视频下采样到码流分辨率

## Streamlit VMR 报告系统

### 首页 (1_🏠_Home.py)

- 显示最近的码流分析报告列表
- 显示最近的 Metrics 对比报告列表
- 支持从 FastAPI 跳转（通过 query params）

### Metrics Analysis 页面 (2_📊_Metrics_Analysis.py)

**重要要求**：Metrics Analysis 页面选择两个 Metrics Analysis 任务（Anchor 和 Test）后生成的对比报告，必须与 Metrics Comparison 页面的报告结构完全一致。

**功能**：
- 选择两个已完成的 Metrics Analysis 任务进行动态对比
- 实时生成 Anchor vs Test 对比报告（不落盘）

**报告结构**（与 Metrics Comparison 页面完全一致）：
1. **Information** - 编码器配置信息对比
2. **Overall** - 整体指标汇总（包含 BD-Rate 汇总）
3. **Metrics** - 质量指标详细对比
   - **RD Curves** - Rate-Distortion 曲线（交互式 Plotly 图表）
   - **Delta** - 指标差异对比（柱状图 + 表格）
   - **Details** - 详细指标数据表格
4. **BD-Rate** - BD-Rate 分析（需要至少 4 个码率点）
   - 汇总表格（带颜色标注）
   - **BD-Rate PSNR** - 独立柱状图
   - **BD-Rate SSIM** - 独立柱状图
   - **BD-Rate VMAF** - 独立柱状图
   - **BD-Rate VMAF-NEG** - 独立柱状图
5. **BD-Metrics** - BD-Metrics 分析
   - 汇总表格（带颜色标注）
   - **BD PSNR** - 独立柱状图
   - **BD SSIM** - 独立柱状图
   - **BD VMAF** - 独立柱状图
   - **BD VMAF-NEG** - 独立柱状图
6. **Performance** - 编码性能对比
   - **Delta** - 性能差异对比（FPS、CPU）
   - **CPU Usage** - CPU 占用率曲线
   - **FPS** - 编码帧率对比
   - **Details** - 详细性能数据
7. **Machine Info** - 执行环境信息（Anchor 和 Test）

**侧边栏目录**：完整的章节导航，包含所有子章节锚点链接

### Metrics Comparison 页面 (3_⚖️_Metrics_Comparison.py)

- Anchor vs Test 对比
- BD-Rate 汇总表
- RD 曲线对比
- 编码性能对比（FPS、CPU）
- 环境信息展示

### Stream Analysis 页面 (4_📈_Stream_Analysis.py)

- 码流分析结果展示
- 逐帧 PSNR/SSIM/VMAF 曲线
- 帧类型分布
- 码率分析

## 报告数据结构

### Stream Analysis 报告 (report_data.json)

```json
{
  "kind": "bitstream_analysis",
  "reference": {
    "label": "source.mp4",
    "width": 1920, "height": 1080, "fps": 30,
    "frames": 300
  },
  "encoded": [
    {
      "label": "encoded_crf23.h265",
      "width": 1280, "height": 720, "fps": 30,
      "codec": "hevc",
      "metrics": {
        "psnr": { "summary": { "psnr_avg": 42.5 }, "frames": [...] },
        "ssim": { "summary": { "ssim_avg": 0.98 }, "frames": [...] },
        "vmaf": { "summary": { "vmaf_mean": 95.2, "vmaf_neg_mean": 94.8 }, "frames": [...] }
      },
      "bitrate": {
        "avg_bitrate_bps": 2500000,
        "frame_types": ["I", "P", "B", ...],
        "frame_sizes": [12345, 2345, ...]
      }
    }
  ]
}
```

### Metrics Comparison 报告 (report_data.json)

```json
{
  "kind": "template_metrics",
  "template_id": "xxx",
  "template_name": "H265 vs H264",
  "rate_control": "crf",
  "bitrate_points": [21, 24, 27, 30],
  "anchor": { "encoder_type": "ffmpeg", "encoder_params": "-c:v libx264 ..." },
  "test": { "encoder_type": "ffmpeg", "encoder_params": "-c:v libx265 ..." },
  "entries": [
    {
      "source": "video1.mp4",
      "anchor": { "encoded": [...] },
      "test": { "encoded": [...] }
    }
  ],
  "bd_metrics": [
    {
      "source": "video1.mp4",
      "bd_rate_psnr": -15.2,
      "bd_rate_ssim": -12.8,
      "bd_rate_vmaf": -18.5,
      "bd_rate_vmaf_neg": -17.2
    }
  ],
  "anchor_environment": { "os": "Darwin", "cpu_model": "Apple M2", ... },
  "test_environment": { ... }
}
```

## API 端点

### 任务 API

- `POST /api/jobs` - 创建任务
- `GET /api/jobs` - 列出任务
- `GET /api/jobs/{job_id}` - 获取任务详情
- `DELETE /api/jobs/{job_id}` - 删除任务

### 模板 API (Metrics Comparison)

- `POST /api/templates` - 创建模板
- `GET /api/templates` - 列出模板
- `GET /api/templates/{template_id}` - 获取模板
- `PUT /api/templates/{template_id}` - 更新模板
- `DELETE /api/templates/{template_id}` - 删除模板
- `POST /api/templates/{template_id}/jobs` - 创建模板任务

### Metrics Analysis API

- `POST /api/metrics-analysis/templates` - 创建模板
- `GET /api/metrics-analysis/templates` - 列出模板
- `POST /api/metrics-analysis/templates/{template_id}/jobs` - 创建任务

## 配置文件 (config.yml)

```yaml
host: "0.0.0.0"
fastapi_port: 8078
streamlit_port: 8079
reports_root_dir: "./data/reports"
jobs_root_dir: "./data/jobs"
templates_root_dir: "./data/templates"
ffmpeg_path: null  # 使用系统默认
ffmpeg_timeout: 3600
log_level: "INFO"
```

## 启动方式

```bash
./run.sh
```

或分别启动：

```bash
# FastAPI
uvicorn src.main:app --host 0.0.0.0 --port 8078

# Streamlit
streamlit run src/1_🏠_Home.py --server.port 8079
```

## 关键文件说明

| 文件 | 说明 |
|------|------|
| `src/services/ffmpeg.py` | FFmpeg 封装，包含编码、指标计算、管道打分 |
| `src/services/bitstream_analysis.py` | 码流分析核心逻辑 |
| `src/services/template_runner.py` | Metrics Comparison 执行器，包含性能监控 |
| `src/services/metrics_analysis_runner.py` | Metrics Analysis 执行器 |
| `src/utils/video_processing.py` | 分辨率/帧率计算、滤镜构建 |
| `src/utils/encoding.py` | 编码命令构建 |
| `src/utils/bd_rate.py` | BD-Rate 计算算法 |
| `src/models/template.py` | 模板数据模型 |
| `src/models/job.py` | 任务数据模型 |
