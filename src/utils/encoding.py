"""
编码工具模块 - 提供编码相关的公共函数

被 template_runner.py 和 metrics_analysis_runner.py 共用
"""
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.models import CommandLog, CommandStatus
from src.models.template import EncoderType
from src.services.ffmpeg import ffmpeg_service
from src.utils.video_processing import build_encode_vf_filter


def now():
    """获取当前时间（带时区）"""
    return datetime.now().astimezone()


@dataclass
class SourceInfo:
    """源视频信息"""
    path: Path
    is_yuv: bool
    width: int
    height: int
    fps: float
    pix_fmt: str = "yuv420p"


def list_sources(source_dir: Path) -> List[Path]:
    """列出目录下的所有文件"""
    return sorted([p for p in source_dir.iterdir() if p.is_file()])


def parse_yuv_name(path: Path) -> Tuple[int, int, float]:
    """
    解析 YUV 文件名获取分辨率和帧率

    文件名格式: name_WxH_FPS.yuv
    例如: video_1920x1080_30.yuv
    """
    import re
    stem = path.stem
    m = re.search(r"_([0-9]+)x([0-9]+)_([0-9]+(?:\.[0-9]+)?)$", stem)
    if not m:
        raise ValueError(f"YUV 文件名不符合格式: {path.name}")
    return int(m.group(1)), int(m.group(2)), float(m.group(3))


async def probe_media(path: Path) -> Tuple[int, int, float]:
    """使用 FFprobe 获取媒体文件信息"""
    info = await ffmpeg_service.get_video_info(path)
    w = info.get("width")
    h = info.get("height")
    fps = info.get("fps")
    if not (w and h and fps):
        raise ValueError(f"无法解析分辨率/FPS: {path}")
    return int(w), int(h), float(fps)


async def collect_sources(source_dir: str) -> List[SourceInfo]:
    """收集源目录下的所有视频文件信息"""
    anchor = Path(source_dir)
    if not anchor.is_dir():
        raise ValueError(f"源目录不存在: {source_dir}")
    files = list_sources(anchor)
    if not files:
        raise ValueError(f"源目录为空: {source_dir}")

    results: List[SourceInfo] = []
    for p in files:
        if p.suffix.lower() == ".yuv":
            w, h, fps = parse_yuv_name(p)
            results.append(SourceInfo(path=p, is_yuv=True, width=w, height=h, fps=fps))
        else:
            w, h, fps = await probe_media(p)
            results.append(SourceInfo(path=p, is_yuv=False, width=w, height=h, fps=fps))
    return results


def encoder_extension(enc: EncoderType) -> str:
    """根据编码器类型返回输出文件扩展名"""
    if enc == EncoderType.X264:
        return ".h264"
    if enc == EncoderType.X265:
        return ".h265"
    if enc == EncoderType.VVENC:
        return ".h266"
    return ".h264"


CONTAINER_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".flv",
    ".ts", ".webm", ".mpg", ".mpeg", ".m4v",
}


def is_container_file(path: Path) -> bool:
    """判断是否为容器格式文件"""
    return path.suffix.lower() in CONTAINER_EXTENSIONS


def build_output_stem(src: Path, rate_control: str, val: float) -> str:
    """构建输出文件名（不含扩展名）"""
    rc = (rate_control or "rc").lower()
    val_str = str(val).rstrip("0").rstrip(".") if isinstance(val, float) else str(val)
    return f"{src.stem}_{rc}_{val_str}"


def output_extension(enc: EncoderType, src: SourceInfo, is_container: bool, params: str = "") -> str:
    """确定输出文件扩展名"""
    if enc == EncoderType.FFMPEG:
        if is_container:
            return src.path.suffix or ".mp4"
        # 根据编码参数确定输出扩展名
        params_lower = params.lower()
        if "libx265" in params_lower or "hevc" in params_lower or "-c:v h265" in params_lower:
            return ".h265"
        if "libx264" in params_lower or "-c:v h264" in params_lower:
            return ".h264"
        if "libvvenc" in params_lower or "vvc" in params_lower:
            return ".h266"
        # 默认返回 .h264
        return ".h264"
    return encoder_extension(enc)


def strip_rc_tokens(enc: EncoderType, params: str) -> List[str]:
    """从参数中移除码率控制相关的 token"""
    tokens = shlex.split(params) if params else []
    cleaned: List[str] = []
    skip_next = False
    ffmpeg_flags = {"-crf", "-b:v"}
    encoder_flags = {"--crf", "--bitrate"}
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if enc == EncoderType.FFMPEG and tok in ffmpeg_flags:
            skip_next = True
            continue
        if enc != EncoderType.FFMPEG and tok in encoder_flags:
            skip_next = True
            continue
        cleaned.append(tok)
    return cleaned


def build_encode_cmd(
    enc: EncoderType,
    params: str,
    rc: str,
    val: float,
    src: SourceInfo,
    output: Path,
    encoder_path: Optional[str] = None,
    shortest_size: Optional[int] = None,
    target_fps: Optional[float] = None,
) -> Tuple[Union[List[str], str], int, int, float]:
    """
    构建编码命令

    Args:
        enc: 编码器类型
        params: 编码参数
        rc: 码率控制模式 (crf/abr)
        val: 码率控制值
        src: 源视频信息
        output: 输出文件路径
        encoder_path: 自定义编码器路径（可选）
        shortest_size: 短边尺寸（可选，不填则使用源视频分辨率）
        target_fps: 目标帧率（可选，不填则使用源视频帧率）

    Returns:
        (cmd, out_width, out_height, out_fps)
        - cmd: 编码命令（List[str] 或管道命令字符串）
        - out_width: 输出宽度
        - out_height: 输出高度
        - out_fps: 输出帧率
    """
    val_str = str(val)
    ffmpeg_path = encoder_path or ffmpeg_service.ffmpeg_path

    # 构建 -vf 滤镜
    vf_filter, out_width, out_height, out_fps = build_encode_vf_filter(
        src_width=src.width,
        src_height=src.height,
        src_fps=src.fps,
        shortest_size=shortest_size,
        target_fps=target_fps,
    )

    if enc == EncoderType.FFMPEG:
        cmd = [ffmpeg_path, "-y", "-nostdin", "-noautorotate", "-an"]
        if src.is_yuv:
            cmd += [
                "-f", "rawvideo",
                "-pix_fmt", src.pix_fmt,
                "-s:v", f"{src.width}x{src.height}",
                "-r", str(src.fps),
            ]
        cmd += ["-i", str(src.path)]

        # 使用 -vf 滤镜进行帧率和分辨率转换
        if vf_filter:
            cmd += ["-vf", vf_filter]

        cmd += strip_rc_tokens(enc, params)
        if rc.lower() == "crf":
            cmd += ["-crf", val_str]
        else:
            cmd += ["-b:v", f"{val_str}k"]
        cmd += [str(output)]
        return cmd, out_width, out_height, out_fps

    # 非 FFmpeg 编码器
    # 这些编码器需要通过管道接收 rawvideo 输入

    # 第一阶段：FFmpeg 解码并输出 rawvideo
    ffmpeg_cmd = [ffmpeg_path, "-y", "-nostdin", "-noautorotate", "-an"]
    if src.is_yuv:
        ffmpeg_cmd += [
            "-f", "rawvideo",
            "-pix_fmt", src.pix_fmt,
            "-s:v", f"{src.width}x{src.height}",
            "-r", str(src.fps),
        ]
    ffmpeg_cmd += ["-i", str(src.path)]

    # 使用 -vf 滤镜进行帧率和分辨率转换
    if vf_filter:
        ffmpeg_cmd += ["-vf", vf_filter]

    # 输出 rawvideo 到 stdout
    ffmpeg_cmd += ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]

    # 第二阶段：独立编码器从 stdin 读取并编码
    encoder_bin = encoder_path if encoder_path else enc.value
    encoder_cmd = [encoder_bin]

    # 添加输入参数
    encoder_cmd += ["--input-res", f"{out_width}x{out_height}"]
    encoder_cmd += ["--fps", str(out_fps)]
    encoder_cmd += ["--input-csp", "i420"]

    # 添加用户参数
    encoder_cmd += strip_rc_tokens(enc, params)

    # 添加码率控制参数
    if rc.lower() == "crf":
        encoder_cmd += ["--crf", val_str]
    else:
        encoder_cmd += ["--bitrate", val_str]

    # 输出文件
    encoder_cmd += ["-o", str(output)]

    # stdin 输入
    encoder_cmd += ["-"]

    # 构建管道命令字符串
    ffmpeg_cmd_str = " ".join(shlex.quote(str(arg)) for arg in ffmpeg_cmd)
    encoder_cmd_str = " ".join(shlex.quote(str(arg)) for arg in encoder_cmd)
    pipeline_cmd = f"{ffmpeg_cmd_str} | {encoder_cmd_str}"

    return pipeline_cmd, out_width, out_height, out_fps


def start_command(job, command_type: str, command: List[str], source_file: Optional[str], storage) -> Optional[CommandLog]:
    """记录命令开始执行"""
    if not job:
        return None
    log = CommandLog(
        command_id=f"{len(job.metadata.command_logs)+1}",
        command_type=command_type,
        command=" ".join(command),
        status=CommandStatus.RUNNING,
        source_file=str(source_file) if source_file else None,
        started_at=now(),
    )
    job.metadata.command_logs.append(log)
    try:
        storage.update_job(job)
    except Exception:
        pass
    return log


def finish_command(job, log: Optional[CommandLog], status: CommandStatus, storage, error: Optional[str] = None) -> None:
    """记录命令执行完成"""
    if not job or not log:
        return
    log.status = status
    log.completed_at = now()
    if error:
        log.error_message = error
    try:
        storage.update_job(job)
    except Exception:
        pass
