"""
Metrics 分析模板执行器（单侧）
"""
import asyncio
import json
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

from src.models import CommandLog, CommandStatus
from src.models.template import EncoderType, EncodingTemplate, TemplateSideConfig, TemplateType
from src.services.storage import job_storage
from src.services.bitstream_analysis import build_bitstream_report
from src.services.ffmpeg import ffmpeg_service
from src.utils.encoding import (
    SourceInfo,
    collect_sources as _collect_sources,
    build_output_stem as _build_output_stem,
    output_extension as _output_extension,
    is_container_file as _is_container_file,
    build_encode_cmd as _build_encode_cmd,
    start_command as _start_command,
    finish_command as _finish_command,
    now as _now,
)


def _env_info() -> Dict[str, str]:
    info = {}
    try:
        info["os"] = platform.platform()
        cpu = platform.processor() or platform.uname().processor
        info["cpu"] = cpu or ""
        info["phys_cores"] = str(psutil.cpu_count(logical=False) or "")
        info["log_cores"] = str(psutil.cpu_count(logical=True) or "")
        info["numa_nodes"] = ""
        info["cpu_percent_start"] = str(psutil.cpu_percent(interval=0.1))
        vm = psutil.virtual_memory()
        info["mem_total"] = str(vm.total)
        info["mem_available"] = str(vm.available)
    except Exception:
        pass
    return info


async def _encode(config: TemplateSideConfig, sources: List[SourceInfo], job=None) -> Dict[str, Tuple[List[Path], int, int, float]]:
    """
    编码源视频

    Returns:
        Dict[str, Tuple[List[Path], int, int, float]]: 源文件名 -> (编码文件列表, 输出宽度, 输出高度, 输出帧率)
    """
    outputs: Dict[str, Tuple[List[Path], int, int, float]] = {}
    out_dir = Path(config.bitstream_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for src in sources:
        file_outputs: List[Path] = []
        out_width, out_height, out_fps = src.width, src.height, src.fps

        for val in config.bitrate_points or []:
            stem = _build_output_stem(src.path, config.rate_control.value if config.rate_control else "rc", val)
            if config.skip_encode:
                matches = list(out_dir.glob(f"{stem}.*"))
                if matches:
                    file_outputs.append(matches[0])
                    continue
                raise FileNotFoundError(f"缺少码流: {stem}")

            ext = _output_extension(config.encoder_type, src, is_container=not src.is_yuv and _is_container_file(src.path), params=config.encoder_params or "")
            output_path = out_dir / f"{stem}{ext}"
            cmd, out_width, out_height, out_fps = _build_encode_cmd(
                enc=config.encoder_type,
                params=config.encoder_params or "",
                rc=config.rate_control.value if config.rate_control else "rc",
                val=val,
                src=src,
                output=output_path,
                shortest_size=config.shortest_size,
                target_fps=config.target_fps,
            )
            log = _start_command(job, "encode", cmd, source_file=str(src.path), storage=job_storage)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(stderr.decode(errors="ignore"))
                _finish_command(job, log, CommandStatus.COMPLETED, storage=job_storage)
            except Exception as exc:
                _finish_command(job, log, CommandStatus.FAILED, storage=job_storage, error=str(exc))
                raise
            file_outputs.append(output_path)
        outputs[src.path.stem] = (file_outputs, out_width, out_height, out_fps)
    return outputs


async def _analyze_single(
    src: SourceInfo,
    encoded_paths: List[Path],
    analysis_dir: Path,
    upscale_to_source: bool,
    target_fps: Optional[float],
    add_command,
    update_status,
):
    analysis_dir.mkdir(parents=True, exist_ok=True)
    report, _summary = await build_bitstream_report(
        reference_path=src.path,
        encoded_paths=encoded_paths,
        analysis_dir=analysis_dir,
        raw_width=src.width if src.is_yuv else None,
        raw_height=src.height if src.is_yuv else None,
        raw_fps=src.fps if src.is_yuv else None,
        raw_pix_fmt=src.pix_fmt,
        upscale_to_source=upscale_to_source,
        target_fps=target_fps,
        add_command_callback=add_command,
        update_status_callback=update_status,
    )
    return report


class MetricsAnalysisRunner:
    async def execute(self, template: EncodingTemplate, job=None) -> Dict[str, Any]:
        if template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
            raise ValueError("模板类型不匹配")
        config = template.metadata.anchor

        sources = await _collect_sources(config.source_dir)
        ordered_sources = sorted(sources, key=lambda s: s.path.name)

        # 准备命令日志回调
        def _add_cmd(command_type: str, command: str, source_file: str = None):
            import shlex
            cmd = shlex.split(command)
            log = _start_command(job, command_type, cmd, source_file=source_file, storage=job_storage)
            return log.command_id if log else None

        def _update_cmd(command_id: str, status: str, error: str = None):
            if not job:
                return
            for cmd_log in job.metadata.command_logs:
                if cmd_log.command_id == command_id:
                    cmd_log.status = CommandStatus(status)
                    now = _now()
                    if status == "running":
                        cmd_log.started_at = now
                    else:
                        cmd_log.completed_at = now
                    if error:
                        cmd_log.error_message = error
                    break
            try:
                job_storage.update_job(job)
            except Exception:
                pass

        encoded_outputs = await _encode(config, ordered_sources, job=job)

        analysis_root = Path(job.job_dir) / "metrics_analysis" if job else Path(template.template_dir) / "metrics_analysis"
        analysis_root.mkdir(parents=True, exist_ok=True)

        entries: List[Dict[str, Any]] = []
        for src in ordered_sources:
            output_info = encoded_outputs.get(src.path.stem)
            if not output_info:
                raise ValueError(f"缺少码流: {src.path.name}")
            paths, _out_width, _out_height, _out_fps = output_info
            if not paths:
                raise ValueError(f"缺少码流: {src.path.name}")
            report = await _analyze_single(
                src,
                paths,
                analysis_root / src.path.stem,
                upscale_to_source=config.upscale_to_source,
                target_fps=config.target_fps,
                add_command=_add_cmd,
                update_status=_update_cmd,
            )
            entries.append(
                {
                    "source": src.path.name,
                    "encoded": report.get("encoded") or [],
                }
            )

        result = {
            "kind": "metrics_analysis_single",
            "template_id": template.template_id,
            "template_name": template.metadata.name,
            "rate_control": config.rate_control.value if config.rate_control else None,
            "bitrate_points": config.bitrate_points,
            "entries": entries,
            "environment": _env_info(),
        }

        data_path = analysis_root / "analyse_data.json"
        try:
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            if job:
                result["data_file"] = str(data_path.relative_to(job.job_dir))
            else:
                result["data_file"] = str(data_path)
        except Exception:
            pass

        return result


metrics_analysis_runner = MetricsAnalysisRunner()
