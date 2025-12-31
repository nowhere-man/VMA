"""
性能监控工具模块
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import psutil

from src.models.template import EncoderType


@dataclass
class PerformanceData:
    """编码性能数据"""
    encoding_fps: Optional[float] = None
    total_encoding_time_s: Optional[float] = None
    total_frames: Optional[int] = None
    cpu_avg_percent: Optional[float] = None
    cpu_max_percent: Optional[float] = None
    cpu_samples: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.encoding_fps is not None:
            result["encoding_fps"] = round(self.encoding_fps, 2)
        if self.total_encoding_time_s is not None:
            result["total_encoding_time_s"] = round(self.total_encoding_time_s, 2)
        if self.total_frames is not None:
            result["total_frames"] = self.total_frames
        if self.cpu_avg_percent is not None:
            result["cpu_avg_percent"] = round(self.cpu_avg_percent, 2)
        if self.cpu_max_percent is not None:
            result["cpu_max_percent"] = round(self.cpu_max_percent, 2)
        if self.cpu_samples:
            result["cpu_samples"] = [round(s, 2) for s in self.cpu_samples]
        return result


def parse_encoder_output(stderr: str, encoder_type: EncoderType) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    """
    解析编码器输出，提取帧数、FPS、总时间
    返回: (frames, fps, total_time_s)
    """
    frames: Optional[int] = None
    fps: Optional[float] = None
    total_time: Optional[float] = None

    if encoder_type == EncoderType.FFMPEG:
        matches = re.findall(r"frame=\s*(\d+).*?fps=\s*([\d.]+).*?elapsed=(\d+):(\d+):([\d.]+)", stderr)
        if matches:
            last_match = matches[-1]
            frames = int(last_match[0])
            fps = float(last_match[1])
            hours = int(last_match[2])
            minutes = int(last_match[3])
            seconds = float(last_match[4])
            total_time = hours * 3600 + minutes * 60 + seconds
    elif encoder_type == EncoderType.X264:
        m = re.search(r"encoded\s+(\d+)\s+frames,\s+([\d.]+)\s+fps", stderr)
        if m:
            frames = int(m.group(1))
            fps = float(m.group(2))
    elif encoder_type == EncoderType.X265:
        m = re.search(r"encoded\s+(\d+)\s+frames\s+in\s+([\d.]+)s\s+\(([\d.]+)\s+fps\)", stderr)
        if m:
            frames = int(m.group(1))
            total_time = float(m.group(2))
            fps = float(m.group(3))
    elif encoder_type == EncoderType.VVENC:
        m = re.search(r"Total Time:\s+([\d.]+)\s+sec.*?Fps\(avg\):\s+([\d.]+).*?encoded Frames\s+(\d+)", stderr)
        if m:
            total_time = float(m.group(1))
            fps = float(m.group(2))
            frames = int(m.group(3))

    return frames, fps, total_time


def get_process_tree_cpu(proc: psutil.Process) -> float:
    """获取进程树（父进程+所有子进程）的CPU占用率总和"""
    total_cpu = 0.0
    try:
        total_cpu += proc.cpu_percent(interval=None)
        for child in proc.children(recursive=True):
            try:
                total_cpu += child.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return total_cpu


async def sample_cpu(pid: int, samples: List[float], stop_event: asyncio.Event) -> None:
    """后台协程：每100ms采样一次CPU占用率"""
    cpu_count = psutil.cpu_count() or 1
    try:
        proc = psutil.Process(pid)
        get_process_tree_cpu(proc)
        await asyncio.sleep(0.1)

        while not stop_event.is_set():
            try:
                raw_cpu = get_process_tree_cpu(proc)
                normalized = raw_cpu / cpu_count
                samples.append(normalized)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            await asyncio.sleep(0.1)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


async def run_encode_with_perf(
    cmd: List[str],
    encoder_type: EncoderType,
) -> Tuple[int, bytes, bytes, PerformanceData]:
    """
    运行编码命令并采集性能数据
    返回: (returncode, stdout, stderr, performance_data)
    """
    perf = PerformanceData()
    cpu_samples: List[float] = []
    stop_event = asyncio.Event()

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    sample_task = asyncio.create_task(sample_cpu(proc.pid, cpu_samples, stop_event))
    start_time = time.time()
    stdout, stderr = await proc.communicate()
    end_time = time.time()

    stop_event.set()
    await sample_task

    perf.cpu_samples = cpu_samples
    if cpu_samples:
        perf.cpu_avg_percent = sum(cpu_samples) / len(cpu_samples)
        perf.cpu_max_percent = max(cpu_samples)

    stderr_str = stderr.decode(errors="ignore")
    frames, fps, total_time = parse_encoder_output(stderr_str, encoder_type)

    if frames is not None:
        perf.total_frames = frames
    if fps is not None:
        perf.encoding_fps = fps
    if total_time is not None:
        perf.total_encoding_time_s = total_time
    else:
        perf.total_encoding_time_s = end_time - start_time

    return proc.returncode or 0, stdout, stderr, perf
