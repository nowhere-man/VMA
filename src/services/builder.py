"""
编码器构建服务

负责从 Git 仓库克隆并构建编码器
"""
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from src.models.schedule import EncoderConfig

logger = logging.getLogger(__name__)


class BuildError(Exception):
    """构建错误"""
    pass


class DependencyError(Exception):
    """依赖错误"""
    pass


class EncoderBuilder:
    """编码器构建器"""

    # 必需的依赖
    REQUIRED_COMMANDS = ["gcc", "cmake", "git", "nasm"]

    def __init__(self, workspace_root: Path):
        """
        初始化构建器

        Args:
            workspace_root: 工作空间根目录
        """
        self.workspace_root = workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    async def check_dependencies(self) -> Tuple[bool, str]:
        """
        检查构建依赖

        Returns:
            Tuple[bool, str]: (是否成功, 错误信息)
        """
        missing = []

        for cmd in self.REQUIRED_COMMANDS:
            if not shutil.which(cmd):
                missing.append(cmd)

            if missing:
                msg = f"Missing dependencies: {', '.join(missing)}"
                logger.error(msg)
                return False, msg

        logger.info("All dependencies checked")
        return True, ""

    async def clone_repository(
        self,
        repo: str,
        branch: str,
        target_dir: Path,
    ) -> Tuple[bool, str]:
        """
        克隆 Git 仓库

        Args:
            repo: 仓库地址
            branch: 分支名
            target_dir: 目标目录

        Returns:
            Tuple[bool, str]: (是否成功, 输出日志)
        """
        if target_dir.exists():
            logger.info(f"Repository already exists: {target_dir}")
            return True, f"Repository already exists: {target_dir}"

        log_output = []

        # 构建克隆命令
        cmd = [
            "git",
            "clone",
            "--depth=1",
            "--single-branch",
            "--branch",
            branch,
            repo,
            str(target_dir),
        ]

        log_output.append(f"Command: {' '.join(cmd)}")
        logger.info(f"Cloning repository: {repo} (branch: {branch})")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            stdout_text = stdout.decode(errors="ignore")
            stderr_text = stderr.decode(errors="ignore")

            log_output.append(stdout_text)
            log_output.append(stderr_text)

            if process.returncode != 0:
                error_msg = f"Git clone failed with code {process.returncode}"
                logger.error(f"{error_msg}\n{stderr_text}")
                return False, "\n".join(log_output)

            logger.info(f"Repository cloned successfully: {target_dir}")
            return True, "\n".join(log_output)

        except Exception as e:
            error_msg = f"Git clone exception: {str(e)}"
            logger.error(error_msg)
            log_output.append(error_msg)
            return False, "\n".join(log_output)

    async def build_encoder(
        self,
        config: EncoderConfig,
        build_dir: Path,
    ) -> Tuple[bool, str]:
        """
        构建编码器

        Args:
            config: 编码器配置
            build_dir: 构建目录

        Returns:
            Tuple[bool, str]: (是否成功, 输出日志)
        """
        log_output = []

        # 构建脚本路径
        script_path = build_dir / config.build_script
        if not script_path.exists():
            error_msg = f"Build script not found: {script_path}"
            logger.error(error_msg)
            return False, error_msg

        logger.info(f"Building encoder with script: {config.build_script}")

        try:
            # 执行构建脚本
            process = await asyncio.create_subprocess_exec(
                str(script_path),
                cwd=build_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            stdout_text = stdout.decode(errors="ignore")
            stderr_text = stderr.decode(errors="ignore")

            log_output.append(stdout_text)
            log_output.append(stderr_text)

            if process.returncode != 0:
                error_msg = f"Build failed with code {process.returncode}"
                logger.error(f"{error_msg}\n{stderr_text}")
                return False, "\n".join(log_output)

            logger.info("Encoder built successfully")
            return True, "\n".join(log_output)

        except Exception as e:
            error_msg = f"Build exception: {str(e)}"
            logger.error(error_msg)
            log_output.append(error_msg)
            return False, "\n".join(log_output)

    def verify_binary(self, binary_path: Path) -> bool:
        """
        验证二进制文件

        Args:
            binary_path: 二进制文件路径

        Returns:
            是否存在且可执行
        """
        if not binary_path.exists():
            logger.error(f"Binary not found: {binary_path}")
            return False

        if not shutil.which(binary_path):
            # 检查文件是否有执行权限
            if not binary_path.stat().st_mode & 0o111:
                logger.warning(f"Binary not executable: {binary_path}")
                # 尝试添加执行权限
                try:
                    binary_path.chmod(0o755)
                    logger.info(f"Added execute permission to: {binary_path}")
                except Exception as e:
                    logger.error(f"Failed to add execute permission: {e}")
                    return False

        logger.info(f"Binary verified: {binary_path}")
        return True

    async def build(
        self,
        config: EncoderConfig,
        repo_name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        完整构建流程

        Args:
            config: 编码器配置
            repo_name: 仓库名称（可选，默认从 repo URL 提取）

        Returns:
            Tuple[bool, str, Optional[Path]]: (是否成功, 日志, 二进制路径)
        """
        log_lines = []
        start_time = datetime.now()

        log_lines.append(f"Build started at: {start_time.isoformat()}")
        log_lines.append(f"Repository: {config.repo}")
        log_lines.append(f"Branch: {config.branch}")
        log_lines.append(f"Build script: {config.build_script}")
        log_lines.append(f"Binary path: {config.binary_path}")
        log_lines.append("=" * 80)

        # 1. 检查依赖
        log_lines.append("\n[1/4] Checking dependencies...")
        success, error = await self.check_dependencies()
        if not success:
            log_lines.append(f"ERROR: {error}")
            return False, "\n".join(log_lines), None
        log_lines.append("OK")

        # 2. 确定仓库名称和目录
        if not repo_name:
            repo_name = config.repo.rstrip("/").split("/")[-1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]

        repo_dir = self.workspace_root / repo_name

        # 3. 克隆仓库
        log_lines.append(f"\n[2/4] Cloning repository to {repo_dir}...")
        success, clone_log = await self.clone_repository(
            repo=config.repo,
            branch=config.branch,
            target_dir=repo_dir,
        )
        log_lines.append(clone_log)
        if not success:
            return False, "\n".join(log_lines), None

        # 4. 执行构建
        log_lines.append(f"\n[3/4] Building encoder...")
        success, build_log = await self.build_encoder(
            config=config,
            build_dir=repo_dir,
        )
        log_lines.append(build_log)
        if not success:
            return False, "\n".join(log_lines), None

        # 5. 验证二进制
        binary_path = repo_dir / config.binary_path
        log_lines.append(f"\n[4/4] Verifying binary: {binary_path}")
        if not self.verify_binary(binary_path):
            error_msg = f"Binary verification failed: {binary_path}"
            log_lines.append(f"ERROR: {error_msg}")
            return False, "\n".join(log_lines), None

        # 完成
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        log_lines.append("\n" + "=" * 80)
        log_lines.append(f"Build completed successfully in {duration:.2f} seconds")
        log_lines.append(f"Binary path: {binary_path}")

        return True, "\n".join(log_lines), binary_path


# 全局单例（需要设置 workspace_root）
_encoder_builder: Optional[EncoderBuilder] = None


def get_encoder_builder(workspace_root: Path) -> EncoderBuilder:
    """
    获取编码器构建器实例

    Args:
        workspace_root: 工作空间根目录

    Returns:
        EncoderBuilder 实例
    """
    global _encoder_builder
    if _encoder_builder is None or _encoder_builder.workspace_root != workspace_root:
        _encoder_builder = EncoderBuilder(workspace_root)
    return _encoder_builder
