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

### 四大功能模块

| 模块 | JobMode | 处理器 | 输出文件 | 用途 |
|------|---------|--------|----------|------|
| Stream Analysis | `bitstream_analysis` | `stream_analysis_runner.py` | `stream_analysis.json` | 分析已有编码视频的质量 |
| Metrics Analysis | `metrics_analysis` | `metrics_analysis_runner.py` | `metrics_analysis.json` | 批量编码源视频+质量分析 |
| Metrics Comparison | `metrics_comparison` | `metrics_comparison_runner.py` | `metrics_comparison.json` | Anchor vs Test 对比分析 |
| **Schedule** | N/A | `scheduler.py` + `schedule_runner.py` | N/A | 定时执行模板+自动编译编码器 |

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

### TemplateSideConfig 数据结构

**文件**：`src/models/template.py`

**字段说明**：
```python
class TemplateSideConfig(BaseModel):
    skip_encode: bool = False                    # 跳过编码
    source_dir: str                              # 源视频目录
    encoder_type: Optional[EncoderType]          # 编码器类型（ffmpeg/x264/x265/vvenc）
    encoder_params: Optional[str]                # 编码器参数
    rate_control: Optional[RateControl]          # 码控模式（crf/abr）
    bitrate_points: List[float]                  # 码率点列表
    bitstream_dir: str                           # 码流输出目录

    # 视频处理配置
    shortest_size: Optional[int]                 # 短边尺寸
    target_fps: Optional[float]                  # 目标帧率
    upscale_to_source: bool = True               # Metrics 策略
    concurrency: int = 1                         # 并发任务数（默认1）
```

**重要字段**：
- `concurrency`：并发任务数，控制同时执行的编码任务数量
  - 默认值：1（串行执行）
  - 适用场景：多视频、多码率点批量编码
  - 技术实现：`asyncio.Semaphore` + `asyncio.gather()`
  - 原子操作：编码 + 性能统计 + 打分

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

## 并发任务执行

### 功能说明

**用途**：在 Metrics Analysis 和 Metrics Comparison 中，支持并发执行多个编码任务以提高效率。

**适用场景**：
- 源视频数量多（如 100 个视频）
- 每个视频需要编码多个码率点（如 4 个点位）
- 总任务数 = 源视频数 × 码率点数（如 100 × 4 = 400 个任务）

### 配置方式

**位置**：模板创建/编辑表单，"视频处理配置"部分

**字段**：`concurrency`（并发任务数）

**默认值**：1（串行执行）

**设置方式**：用户手动输入正整数

### 技术实现

**原子操作**：每个任务包含"编码+性能统计+打分"三个步骤

**并发控制**：使用 `asyncio.Semaphore` 限制同时运行的任务数

**代码位置**：
- `src/services/metrics_comparison_runner.py:_encode_side()`（Metrics Comparison）
- `src/services/metrics_analysis_runner.py:_encode()`（Metrics Analysis）

**实现模式**：
```python
async def _encode_side(...) -> Tuple[Dict, Dict]:
    concurrency = side.concurrency or 1
    semaphore = asyncio.Semaphore(concurrency)

    async def encode_single_task(src, val, src_idx, point_idx):
        async with semaphore:
            # 执行编码 + 性能监控 + 打分
            return src_idx, point_idx, out_path, perf

    # 创建所有任务
    tasks = []
    for src_idx, src in enumerate(sources):
        for point_idx, val in enumerate(bitrate_points):
            tasks.append(encode_single_task(src, val, src_idx, point_idx))

    # 并发执行
    results = await asyncio.gather(*tasks)

    # 按原始顺序重组结果
    # ...
```

### 特性说明

**优点**：
- 大幅提升多视频、多码率点场景的执行效率
- 用户可根据机器性能灵活调整并发数
- 保持结果顺序不变

**限制**：
- 不自动检测 CPU 核心数，由用户手动指定
- 任何任务失败会立即停止所有任务（fail-fast）
- 不提供进度反馈

**注意事项**：
- 并发数过高可能导致资源竞争（CPU、内存、磁盘 I/O）
- 建议根据机器性能合理设置（如物理核心数的 50-80%）
- 默认值为 1 保证稳定性和兼容性

---

## Schedule 定时任务（第四大功能模块）

### 功能概述

**用途**：定时执行模板任务，每次执行前自动从 Git 仓库编译指定编码器

**核心特性**：
- 自动从 Git 仓库下载并编译编码器
- 灵活的调度策略（不重复/每天/每周/每月）
- 支持路径覆盖（Schedule 指定的编码器路径优先）
- 完整的执行历史和构建日志
- 任务命名格式：`Schedule: <schedule_name> - <template_name>`

### 数据模型

**文件**：`src/models/schedule.py`

#### ScheduleMetadata
```python
class ScheduleMetadata(BaseModel):
    schedule_id: str                        # Schedule ID
    name: str                                # Schedule 名称
    description: Optional[str]               # 描述

    # 编码器配置
    encoder_type: str                        # ffmpeg/x264/x265/vvenc
    encoder_config: EncoderConfig            # 仓库、分支、构建脚本、二进制路径

    # 模板配置
    template_id: str                          # 关联的模板 ID
    template_type: str                        # metrics_analysis/metrics_comparison
    template_name: str                        # 模板名称

    # 调度配置
    start_time: datetime                      # 首次执行时间
    repeat: ScheduleRepeat                     # none/daily/weekly/monthly

    # 状态
    status: ScheduleStatus                     # active/paused/disabled

    # 执行信息
    last_execution: Optional[datetime]         # 最近执行时间
    last_execution_status: Optional[str]       # success/failed
    last_execution_job_id: Optional[str]       # 最近执行的任务 ID
    next_execution: Optional[datetime]          # 下次执行时间
```

#### EncoderConfig
```python
class EncoderConfig(BaseModel):
    repo: str         # Git 仓库地址
    branch: str       # 分支名
    build_script: str # 构建脚本（在仓库根目录执行）
    binary_path: str  # 构建后的二进制路径（相对于仓库根目录）
```

#### ScheduleExecution
```python
class ScheduleExecution(BaseModel):
    execution_id: str       # 执行 ID
    schedule_id: str        # Schedule ID
    executed_at: datetime    # 执行时间
    job_id: str             # 生成的任务 ID
    build_status: str       # 构建状态 (success/failed/skipped)
    build_log_path: str     # 构建日志路径（相对于 schedule 目录）
    error_message: str      # 错误信息
```

### 存储结构

```
data/
  schedules/
    {schedule_id}/
      schedule.yml              # Schedule 元数据
      executions.yml            # 执行历史（最近 100 条）
      workspace/                # 构建工作区（每次清理）
        repo/                   # 代码仓库（每次删除重建）
      logs/
        build-{timestamp}.log   # 构建日志
```

**schedule.yml 示例**：
```yaml
schedule_id: "sched_abc123"
name: "Nightly FFmpeg Test"
encoder_type: "ffmpeg"
encoder_config:
  repo: "https://git.ffmpeg.org/ffmpeg.git"
  branch: "master"
  build_script: "configure --enable-static && make -j$(nproc)"
  binary_path: "ffmpeg"
template_id: "tpl_xyz789"
template_type: "metrics_comparison"
template_name: "FFmpeg Preset Comparison"
start_time: "2025-01-01T02:30:00"
repeat: "daily"
status: "active"
created_at: "2025-01-01T10:00:00"
last_execution: "2025-01-01T02:30:00"
last_execution_status: "success"
next_execution: "2025-01-02T02:30:00"
```

### 核心服务

#### 1. Schedule 存储服务
**文件**：`src/services/schedule_storage.py`

```python
class ScheduleStorage:
    def create_schedule(schedule: ScheduleMetadata) -> None
    def get_schedule(schedule_id: str) -> Optional[ScheduleMetadata]
    def list_schedules() -> List[ScheduleMetadata]
    def update_schedule(schedule_id: str, schedule: ScheduleMetadata) -> None
    def delete_schedule(schedule_id: str) -> None

    def add_execution(schedule_id: str, execution: ScheduleExecution) -> None
    def list_executions(schedule_id: str, limit: int = 100) -> List[ScheduleExecution]

    def save_build_log(schedule_id: str, log_filename: str, content: str) -> None
    def get_build_log(schedule_id: str, log_filename: str) -> Optional[str]
```

#### 2. 编码器构建服务
**文件**：`src/services/builder.py`

**功能**：
- 依赖检查：gcc, cmake, git, nasm
- Git clone：使用 `--depth=1 --single-branch --branch` 最小化下载
- 执行构建脚本
- 验证二进制文件存在性和可执行性

**核心方法**：
```python
class EncoderBuilder:
    async def build(
        schedule_id: str,
        encoder_config: EncoderConfig,
        log_file: Path,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        构建编码器

        Returns:
            (success, binary_path, error_message)
        """
```

**构建流程**：
1. 检查构建依赖
2. 清理并创建工作区 `data/schedules/{schedule_id}/workspace`
3. Clone 指定分支（depth=1, single-branch）
4. 执行构建脚本
5. 验证二进制存在

#### 3. Schedule 执行服务
**文件**：`src/services/schedule_runner.py`

**功能**：
- 执行编码器构建
- 加载模板并覆盖 `encoder_path`
- 创建和执行任务
- 记录执行历史

**核心方法**：
```python
class ScheduleRunner:
    async def execute(schedule: ScheduleMetadata) -> str:
        """
        执行 Schedule，返回 job_id

        流程：
        1. 构建编码器
        2. 加载模板
        3. 覆盖 encoder_path（Schedule 指定的路径优先）
        4. 创建 Job
        5. 执行 Job
        6. 记录执行历史
        """
```

**路径覆盖机制**：
```python
# 如果 Schedule 指定的二进制路径与模板中的 encoder_path 不一致
# 使用 Schedule 指定的路径覆盖模板路径

def _override_encoder_path(template, binary_path: str):
    if template.metadata.template_type == "metrics_analysis":
        template.metadata.anchor.encoder_path = binary_path
    else:
        template.metadata.anchor.encoder_path = binary_path
        if template.metadata.test:
            template.metadata.test.encoder_path = binary_path
```

#### 4. 调度器服务
**文件**：`src/services/scheduler.py`

**技术栈**：APScheduler 3.10+ (AsyncIOScheduler)

**核心功能**：
- 启动时加载所有 active 的 Schedules
- 支持 Cron 和 Date 两种触发器
- 暂停/恢复/立即执行
- 自动计算下次执行时间

**Trigger 规则**：
```python
# 不重复（一次性）
DateTrigger(run_date=schedule.start_time)

# 每天
CronTrigger(hour=start_time.hour, minute=start_time.minute)

# 每周
CronTrigger(
    day_of_week=start_time.weekday(),
    hour=start_time.hour,
    minute=start_time.minute,
)

# 每月
CronTrigger(
    day=start_time.day,
    hour=start_time.hour,
    minute=start_time.minute,
)
```

**全局单例**：
```python
from src.services.scheduler import scheduler_service

# 启动（main.py 中）
await scheduler_service.start()

# 关闭
await scheduler_service.shutdown()
```

### API 端点

**文件**：`src/api/schedules.py`

#### 基础 CRUD
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/schedules` | 创建 Schedule |
| GET | `/api/schedules` | 列出所有 Schedules |
| GET | `/api/schedules/{schedule_id}` | 获取 Schedule 详情 |
| PUT | `/api/schedules/{schedule_id}` | 编辑 Schedule（不能修改 encoder_config） |
| DELETE | `/api/schedules/{schedule_id}` | 删除 Schedule |

#### 操作端点
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/schedules/{schedule_id}/pause` | 暂停 Schedule |
| POST | `/api/schedules/{schedule_id}/resume` | 恢复 Schedule |
| POST | `/api/schedules/{schedule_id}/trigger` | 立即执行一次 |
| POST | `/api/schedules/{schedule_id}/copy` | 复制 Schedule |

#### 执行历史
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/schedules/{schedule_id}/executions` | 获取执行历史 |
| GET | `/api/schedules/{schedule_id}/executions/{execution_id}` | 获取单次执行详情 |
| GET | `/api/schedules/{schedule_id}/logs/{log_filename}` | 获取构建日志 |

#### 模板筛选
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/templates?encoder_type={type}` | 筛选 Metrics Comparison 模板 |
| GET | `/api/metrics-analysis/templates?encoder_type={type}` | 筛选 Metrics Analysis 模板 |

### 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| Schedule 列表 | `/schedules` | 显示所有 Schedule，支持操作 |
| 创建 Schedule | `/schedules/new` | 创建新 Schedule |
| Schedule 详情 | `/schedules/{schedule_id}` | 查看完整信息、执行历史、构建日志 |
| 编辑 Schedule | `/schedules/{schedule_id}/edit` | 编辑 Schedule（不能修改编码器配置） |

### 路径冲突提醒机制

**触发条件**：模板中的 `encoder_path` 与 Schedule 指定的二进制路径不一致

**UI 表现**：
```
⚠️ 路径冲突提醒
模板中的编码器路径：/usr/local/bin/ffmpeg
Schedule 指定的二进制路径：/root/ffmpeg-build/ffmpeg
将使用 Schedule 指定的路径
☐ 我已知晓，继续创建
```

**强制确认**：
- 用户必须勾选复选框才能提交
- 如果路径一致，不显示此提醒

### 使用流程

#### 1. 创建 Schedule
1. 访问首页，点击"定时任务"
2. 点击"创建 Schedule"
3. 填写编码器配置：
   - 编码器类型（ffmpeg/x264/x265/vvenc）
   - Git 仓库地址
   - 分支名
   - 构建脚本
   - 二进制路径（相对于仓库根目录）
4. 选择模板：
   - 模板类型
   - 模板（自动筛选匹配编码器类型的模板）
   - 如果路径不一致，确认冲突提醒
5. 设置调度：
   - 执行时间（精确到分钟）
   - 重复周期（不重复/每天/每周/每月）
6. 保存

#### 2. 管理 Schedule
- **列表页**：查看所有 Schedule，支持暂停/恢复/触发/复制/删除
- **详情页**：查看完整信息、执行历史、构建日志
- **编辑**：修改名称、描述、模板、时间、周期（编码器配置不可修改）

#### 3. 执行流程
每次触发时自动执行：
1. 清理工作区（删除旧代码）
2. Git clone 指定分支（depth=1, single-branch）
3. 执行构建脚本
4. 验证二进制存在
5. 加载模板并覆盖 `encoder_path`
6. 创建任务（任务名：`Schedule: <schedule_name> - <template_name>`）
7. 执行任务（复用 metrics_analysis_runner 或 metrics_comparison_runner）
8. 记录执行历史和构建日志

### ⚠️ 注意事项

1. **构建依赖**：系统必须已安装 gcc, cmake, git, nasm
2. **Git 策略**：每次删除旧代码重新 clone（不保留缓存）
3. **路径格式**：二进制路径相对于仓库根目录
4. **任务命名**：生成的任务不添加日期时间前缀（与手动创建的任务区分方式：通过 `schedule_id` 关联）
5. **失败处理**：构建失败时创建失败任务，在任务管理页显示错误原因
6. **资源占用**：构建编码器可能消耗大量 CPU 和磁盘 I/O
7. **调度器持久化**：APScheduler 不支持持久化，重启后重新加载 active 的 Schedules
8. **一次性任务**：执行一次后自动变为 disabled 状态

### 编码器路径字段说明

**Bug 修复**：在实现 Schedule 功能时，修复了模板中 `encoder_path` 字段未被使用的问题

**字段含义**：
- **未填写**：使用系统 PATH 中的编码器（如 `ffmpeg`）
- **已填写**：使用指定的绝对路径（如 `/usr/local/bin/ffmpeg`）

**使用位置**：
- Metrics Analysis 模板：`anchor.encoder_path`
- Metrics Comparison 模板：`anchor.encoder_path` 和 `test.encoder_path`

**Schedule 覆盖机制**：
- Schedule 执行时，无论模板中 `encoder_path` 是否填写
- 都会使用 Schedule 构建的二进制路径覆盖模板的 `encoder_path`

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
| `src/models/template.py` | 模板数据模型 | `TemplateSideConfig.concurrency` 字段 |

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
| Stream Analysis | `encoded[i].metrics.psnr.summary.psnr_avg` | `item.get("metrics").get("psnr").get("summary")` |
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

### 5. 并发任务配置
- 默认值为 1（串行），不是自动检测 CPU 核心数
- 并发数过高可能导致资源竞争（CPU/内存/磁盘 I/O）
- 任何任务失败会立即停止所有任务（fail-fast）
- 结果顺序保持不变（通过索引追踪重组）

---

## 用户明确要求

1. **数据结构统一**：所有 Metrics 类型报告使用相同数据结构（无 metrics 包装器）
2. **代码复用**：性能监控、BD-Rate 计算、指标解析等功能模块化
3. **报告结构一致**：任务对比报告和模板对比报告结构完全相同
4. **交互体验**：侧边栏导航、平滑滚动、统一视觉风格
5. **并发任务执行**：
   - 支持用户手动配置并发数（默认为 1）
   - 不自动检测 CPU 核心数，简化实现
   - 原子操作：编码 + 性能统计 + 打分
   - 任何失败立即停止所有任务（fail-fast）
