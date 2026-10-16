#!/usr/bin/env python3
"""发布校验回归测试：安装 PyYAML 后运行 python3 packaging/test_release.py。"""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


class ReleaseChecksums(unittest.TestCase):
    def run_checksums(self, job, directory):
        # 执行工作流本身的校验步骤，用临时文件代替发布包，不触发构建或发布。
        step = next(step for step in WORKFLOW["jobs"][job]["steps"] if step.get("id") == "checksums")
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
            cwd=directory,
            capture_output=True,
            text=True,
        )

    def make_artifact(self, directory, filename):
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / filename
        archive.write_bytes(f"测试发布包：{filename}".encode())
        result = self.run_checksums("build", directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        return archive

    def test_each_platform_artifact(self):
        for filename in ("lantern-v0.1.0-windows-x86_64.zip", "lantern-dev-1234567-linux-x86_64.tar.gz"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(prefix="提灯 校验 ") as tmp:
                directory = Path(tmp)
                archive = self.make_artifact(directory, filename)
                expected = f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {filename}\n"
                self.assertEqual((directory / "SHA256SUMS.txt").read_text(), expected)

    def test_no_archive_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotEqual(self.run_checksums("build", tmp).returncode, 0)

    def test_publish_merges_and_rejects_damaged_artifacts(self):
        for damage in (None, "篡改发布包", "缺少发布包", "缺少校验文件"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory(prefix="提灯 发布 ") as tmp:
                directory = Path(tmp)
                windows = self.make_artifact(
                    directory / "lantern-windows-x86_64", "lantern-v0.1.0-windows-x86_64.zip"
                )
                linux = self.make_artifact(
                    directory / "lantern-linux-x86_64", "lantern-v0.1.0-linux-x86_64.tar.gz"
                )
                expected = sorted(
                    f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}"
                    for archive in (windows, linux)
                )
                if damage == "篡改发布包":
                    windows.write_bytes(b"changed")
                elif damage == "缺少发布包":
                    windows.unlink()
                elif damage == "缺少校验文件":
                    (windows.parent / "SHA256SUMS.txt").unlink()
                result = self.run_checksums("publish", directory)
                if damage is not None:
                    self.assertNotEqual(result.returncode, 0, "损坏的产物不能进入发布步骤")
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sorted((directory / "SHA256SUMS.txt").read_text().splitlines()), expected)
                self.assertTrue((directory / windows.name).is_file())
                self.assertTrue((directory / linux.name).is_file())


if __name__ == "__main__":
    unittest.main()
