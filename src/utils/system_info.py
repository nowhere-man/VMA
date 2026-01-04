"""
系统信息采集模块

提供跨平台的系统环境信息采集功能，包括 CPU、内存、操作系统等信息。
"""
import platform
import subprocess
from typing import Any, Dict

import psutil


def get_cpu_brand() -> str:
    """跨平台获取 CPU 品牌/型号名称"""
    # macOS: 使用 sysctl
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

    # Linux: 读取 /proc/cpuinfo
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":")[1].strip()
        except Exception:
            pass

    # Windows: 使用 wmic 或注册表
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and l.strip() != "Name"]
                if lines:
                    return lines[0]
        except Exception:
            pass

    # 回退到 platform.processor()
    return platform.processor() or "Unknown"


def get_env_info() -> Dict[str, Any]:
    """
    获取系统环境信息

    Returns:
        包含以下字段的字典：
        - execution_time: 执行时间
        - os, os_version, os_full: 操作系统信息
        - cpu_arch, cpu_model: CPU 架构和型号
        - cpu_phys_cores, cpu_log_cores: 物理核心数和逻辑核心数
        - cpu_percent_before: CPU 占用率
        - cpu_freq_mhz: CPU 主频（MHz）
        - numa_nodes: NUMA 节点数（仅 Linux）
        - mem_total_gb, mem_used_gb, mem_available_gb: 内存信息（GB）
        - mem_percent_used: 内存使用率
        - linux_distro: Linux 发行版（仅 Linux）
        - hostname: 主机名
    """
    info: Dict[str, Any] = {}
    try:
        # 执行时间
        from datetime import datetime
        info["execution_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 操作系统
        info["os"] = platform.system()
        info["os_version"] = platform.release()
        info["os_full"] = platform.platform()

        # CPU 信息
        info["cpu_arch"] = platform.machine()  # x86_64, arm64, aarch64 等
        info["cpu_model"] = get_cpu_brand()   # Apple M2, Intel Xeon 等
        info["cpu_phys_cores"] = psutil.cpu_count(logical=False) or 0
        info["cpu_log_cores"] = psutil.cpu_count(logical=True) or 0
        info["cpu_percent_before"] = round(psutil.cpu_percent(interval=0.1), 1)

        # CPU 主频（MHz）
        try:
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                info["cpu_freq_mhz"] = round(cpu_freq.current, 2)
        except Exception:
            pass

        # NUMA nodes
        try:
            if platform.system() == "Linux":
                result = subprocess.run(
                    ["lscpu"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if line.startswith("NUMA node(s):"):
                            info["numa_nodes"] = int(line.split(":")[1].strip())
                            break
        except Exception:
            pass

        # 内存信息（转换为 GB）
        vm = psutil.virtual_memory()
        info["mem_total_gb"] = round(vm.total / (1024 ** 3), 2)
        info["mem_used_gb"] = round(vm.used / (1024 ** 3), 2)
        info["mem_available_gb"] = round(vm.available / (1024 ** 3), 2)
        info["mem_percent_used"] = round(vm.percent, 1)

        # Linux 发行版信息
        if platform.system() == "Linux":
            try:
                result = subprocess.run(
                    ["lsb_release", "-d"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    info["linux_distro"] = result.stdout.split(":", 1)[1].strip() if ":" in result.stdout else result.stdout.strip()
                else:
                    # 尝试读取 /etc/os-release
                    try:
                        with open("/etc/os-release", "r") as f:
                            for line in f:
                                if line.startswith("PRETTY_NAME="):
                                    info["linux_distro"] = line.split("=", 1)[1].strip().strip('"')
                                    break
                    except Exception:
                        pass
            except Exception:
                pass

        # 主机名
        info["hostname"] = platform.node()

    except Exception:
        pass
    return info
