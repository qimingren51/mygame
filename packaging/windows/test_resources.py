#!/usr/bin/env python3
"""验证 Windows 资源；传入 --exe 时同时检查最终 PE，详见本目录 README。"""

import argparse
import struct
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "packaging/windows/lantern.ico"
MANIFEST = ROOT / "packaging/windows/lantern.manifest"
SIZES = (16, 24, 32, 48, 64, 128, 256)


class WindowsResources(unittest.TestCase):
    exe = None

    def check_manifest(self, data):
        root = ET.fromstring(data)
        self.assertEqual(root.tag, "{urn:schemas-microsoft-com:asm.v1}assembly")
        self.assertEqual(root.get("manifestVersion"), "1.0")
        asm = "{urn:schemas-microsoft-com:asm.v3}"
        level = root.find(
            f"{asm}trustInfo/{asm}security/{asm}requestedPrivileges/{asm}requestedExecutionLevel"
        )
        self.assertIsNotNone(level, "缺少权限声明")
        self.assertEqual(level.attrib, {"level": "asInvoker", "uiAccess": "false"})
        settings = root.find(f"{asm}application/{asm}windowsSettings")
        self.assertIsNotNone(settings, "缺少 Windows 设置")
        for year, name, value in (
            (2005, "dpiAware", "true/pm"),
            (2016, "dpiAwareness", "PerMonitorV2, PerMonitor"),
            (2016, "longPathAware", "true"),
            (2019, "activeCodePage", "UTF-8"),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    settings.findtext(f"{{http://schemas.microsoft.com/SMI/{year}/WindowsSettings}}{name}"),
                    value,
                )

    def test_manifest(self):
        self.check_manifest(MANIFEST.read_bytes())

    def test_icon_sizes_and_art_source(self):
        with Image.open(ICON) as icon, Image.open(ROOT / "web/lantern/icons/icon-512.png") as source:
            self.assertEqual(icon.ico.sizes(), {(size, size) for size in SIZES})
            for size in SIZES:
                with self.subTest(size=size):
                    expected = source.convert("RGBA")
                    expected.thumbnail((size, size), Image.Resampling.LANCZOS, reducing_gap=None)
                    self.assertEqual(
                        icon.ico.getimage((size, size)).convert("RGBA").tobytes(), expected.tobytes()
                    )

    def test_exe_resources(self):
        if self.exe is None:
            self.skipTest("未指定 --exe，只检查仓库资源")
        import pefile

        with pefile.PE(str(self.exe)) as pe:
            def resource(kind, resource_id):
                # 按类型和编号查找，不能接受系统关联图标或其他编号的清单。
                kinds = [entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == kind]
                self.assertEqual(len(kinds), 1, f"缺少资源类型 {kind}")
                entries = [entry for entry in kinds[0].directory.entries if entry.id == resource_id]
                self.assertEqual(len(entries), 1, f"缺少资源 {kind}/{resource_id}")
                data = entries[0].directory.entries[0].data.struct
                return pe.get_data(data.OffsetToData, data.Size)

            self.check_manifest(resource(24, 1))
            # RT_GROUP_ICON 的条目引用 RT_ICON；逐帧与仓库 ICO 比较，验证全部尺寸真正进入 EXE。
            group = resource(14, 1)
            self.assertEqual(struct.unpack_from("<HHH", group), (0, 1, len(SIZES)))
            ico = ICON.read_bytes()
            self.assertEqual(struct.unpack_from("<HHH", ico), (0, 1, len(SIZES)))
            for index in range(len(SIZES)):
                width, height, colors, reserved, planes, bits, length, icon_id = struct.unpack_from(
                    "<BBBBHHIH", group, 6 + 14 * index
                )
                expected = struct.unpack_from("<BBBBHHII", ico, 6 + 16 * index)
                # ICO 的 PNG 帧可将 planes 留为 0；资源编译器会将它规范化为 1。
                self.assertIn(planes, (0, 1))
                self.assertEqual((width, height, colors, reserved), expected[:4])
                self.assertEqual((bits, length), expected[5:7])
                self.assertEqual(resource(3, icon_id), ico[expected[7]:expected[7] + length])

            cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
            version = cargo["workspace"]["package"]["version"]
            values = {
                key.decode("utf-8"): value.decode("utf-8")
                for infos in pe.FileInfo
                for info in infos if info.Key == b"StringFileInfo"
                for table in info.StringTable
                for key, value in table.entries.items()
            }
            for key, expected in {
                "ProductName": "提灯夜行",
                "FileDescription": "提灯夜行",
                "OriginalFilename": "lantern.exe",
                "FileVersion": version,
                "ProductVersion": version,
            }.items():
                self.assertEqual(values.get(key), expected, key)
            major, minor, patch = map(int, version.split("-")[0].split("+")[0].split("."))
            fixed = pe.VS_FIXEDFILEINFO[0]
            numeric_version = (major << 16 | minor, patch << 16)
            self.assertEqual((fixed.FileVersionMS, fixed.FileVersionLS), numeric_version)
            self.assertEqual((fixed.ProductVersionMS, fixed.ProductVersionLS), numeric_version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="需要验证资源的 lantern.exe")
    WindowsResources.exe = parser.parse_args().exe
    unittest.main(argv=[__file__])
