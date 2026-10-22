"""Regression tests, including the user-supplied packages when available."""

import hashlib
import io
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

from bank_volume import (
    GROUPS,
    SAMPLES,
    VOICE_BUSES,
    FormatError,
    Package,
    Scan,
    Target,
    classify,
    export,
    gains_checked,
    is_metadata_bank,
    nested_events,
    parse_bank,
    patches_for,
    read_metadata,
    string_table,
)

KNOWN_SAMPLES = ("RCSM_Build_September_7_2026.zip", "OPEX+Overhaul+1.0.7.zip")


class GainTests(unittest.TestCase):
    def test_low_original_gain_never_gets_louder_when_reduced(self):
        for original in (-200.0, -100.0, -80.0, -6.0, 0.0, 6.0):
            scan = SimpleNamespace(targets=[Target("a.bank", "event:/test", "test", "missile", "route", 0, original)])
            for percent in (0, 1, 25, 50, 99):
                gains = dict.fromkeys(GROUPS, 100)
                gains["missile"] = percent
                edits = patches_for(scan, gains).get("a.bank", [])
                if edits:
                    self.assertLessEqual(edits[0]["new_db"], original)

    def test_percent_means_amplitude_ratio_and_100_is_identity(self):
        scan = SimpleNamespace(targets=[Target("a.bank", "event:/test", "test", "missile", "route", 0, 0.0)])
        gains = dict.fromkeys(GROUPS, 100)
        self.assertEqual(patches_for(scan, gains), {})
        for percent in (25, 50, 80, 125, 200, 400):
            gains["missile"] = percent
            db = patches_for(scan, gains)["a.bank"][0]["new_db"]
            self.assertAlmostEqual(10 ** (db / 20), percent / 100, places=6)

    def test_invalid_gains_rejected(self):
        for value in (-1, 401, math.nan, math.inf):
            gains = dict.fromkeys(GROUPS, 100)
            gains["missile"] = value
            with self.assertRaises(ValueError):
                gains_checked(gains)

    def test_missiles_do_not_include_launch_warning_or_rocket(self):
        cases = {
            "event:/aircraft/weapon/missile_med_fly": "missile",
            "event:/aircraft/weapon/missile_med_start": "missile_launch",
            "event:/aircraft/weapon/rocket_fly": "rocket_fly",
            "event:/aircraft/gui/alarm_rocket": "rwr",
            "event:/aircraft/gui/vws/betty/vws_missile": "vws",
            "snapshot:/engine_player": None,
            "event:/naval/engines/ship_engine": "naval_engines",
            "event:/naval/weapon/cannon_large": "naval_weapons",
            "event:/naval/ambient/sea": "naval_effects",
            "event:/aircraft/music/battle": "music",
            "event:/infantry/player/rifle_shot": None,
        }
        for event, expected in cases.items():
            self.assertEqual(classify(event, ""), expected)

    def test_bad_archive_paths_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../outside.bank", "/absolute.bank", "folder/../../a.bank", "C:/a.bank", "a\\b.bank"):
                path = Path(directory) / "bad.zip"
                info = zipfile.ZipInfo("placeholder")
                # ZipInfo turns a backslash into a slash on Windows, so set the stored name directly.
                info.filename = name
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(info, b"test")
                with self.assertRaises(FormatError):
                    Package(path)

    def test_unsupported_inputs_explain_why(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cases = {
                "audio-only/_crew_dialogs_ground_fr.assets.bank": "只有 1 个 .assets.bank",
                "spread/ru/_crew_dialogs_ground_ru.bank": "分散在",
                "spread/en/_crew_dialogs_ground_en.bank": "分散在",
                "variants/A/masterbank.strings.bank": "2 套音效",
                "variants/B/masterbank.strings.bank": "2 套音效",
                "no-bank/readme.txt": "没有找到 FMOD",
            }
            for name in cases:
                (base / name).parent.mkdir(parents=True, exist_ok=True)
                (base / name).write_bytes(b"test")
            for name, reason in cases.items():
                with self.assertRaisesRegex(FormatError, reason):
                    Scan(base / name.split("/")[0])
            for name, magic, reason in (("a.rar", b"Rar!\x1a\x07\x01\x00", "RAR"), ("a.7z", b"7z\xbc\xaf\x27\x1c", "7z"), ("a.zip", b"test", "不是 ZIP")):
                (base / name).write_bytes(magic + bytes(64))
                with self.assertRaisesRegex(FormatError, reason):
                    Package(base / name)

    def test_program_outside_repo_exports_next_to_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "wt-sound-volume.exe"
            code = f"import sys; sys.frozen = True; sys.executable = {str(program)!r}; import bank_volume; print(bank_volume.OUTPUT_ROOT)"
            output = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent, capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(Path(output), program.resolve().parent / "exports")

    def test_truncated_header_rejected(self):
        with self.assertRaises(FormatError):
            read_metadata(io.BytesIO(b"RIFF"), 4)


class SampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The expected counts below belong to these two releases.
        cls.sources = [SAMPLES / name for name in KNOWN_SAMPLES if (SAMPLES / name).is_file()]
        if not cls.sources:
            raise unittest.SkipTest("No local sample packages")
        cls.scans = [Scan(source) for source in cls.sources]

    def sample(self, prefix):
        found = [s for s in self.sources if s.name.startswith(prefix)]
        if not found:
            self.skipTest(f"Needs the {prefix} sample in samples/")
        return found[0]

    def test_actual_samples_have_all_missiles_and_separate_enemy_engines(self):
        for scan in self.scans:
            with self.subTest(source=scan.source):
                self.assertEqual(scan.counts["missile"], 3)
                self.assertGreater(scan.counts["missile_launch"], 0)
                self.assertGreater(scan.counts["ground_engine_enemy"], 200)
                self.assertGreater(scan.counts["tracks_enemy"], 0)
                self.assertEqual(scan.counts["rwr"], 6)
                self.assertEqual(scan.counts["crew_ground"], 1)
                self.assertEqual(scan.unpatchable, [])
                self.assertGreater(scan.snapshots, 0)
                self.assertGreater(scan.unnamed, 0)

    def test_shared_voice_routes_never_get_both_parent_and_event_patches(self):
        for scan in self.scans:
            events = {t.event for t in scan.targets}
            self.assertNotIn("event:/aircraft/gui/radio_click", events)
            self.assertTrue(any(e["event"] == "event:/aircraft/gui/radio_click" and e["group"] == "crew_common" for e in scan.shared_events))
            self.assertIsNone(classify("event:/aircraft/gui/radio_click", "bus:/dialogs/crew_common"))
            self.assertIsNone(classify("event:/dialogs_crew_ground/test", "bus:/dialogs/dialogs/crew_ground/new/crew"))

    def test_evib_references_mark_nested_events(self):
        # Named events are the ones the game starts by path, and unnamed ones are nested.
        # The voice pack mode relies on EVIB chunks telling the two apart.
        for source in self.sources:
            with PackageContext(source) as package:
                strings = string_table(package.metadata("masterbank.strings.bank"))
                named = unnamed = named_nested = unnamed_nested = 0
                banks = [package.metadata(name) for name in package.files if "/" not in name and is_metadata_bank(name)]
                nested = nested_events(banks)
                for data in banks:
                    for guid, _ in parse_bank(data)[1]:
                        path = strings.get(guid, "")
                        if path.startswith("snapshot:"):
                            continue
                        if path:
                            named += 1
                            named_nested += guid in nested
                        else:
                            unnamed += 1
                            unnamed_nested += guid in nested
            with self.subTest(source=source.name):
                self.assertLess(named_nested / named, 0.01)
                self.assertGreater(unnamed_nested / unnamed, 0.95)

    def test_voice_pack_without_strings_adjusts_top_level_events(self):
        for source, scan in zip(self.sources, self.scans):
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                pack = base / "pack"
                pack.mkdir()
                with zipfile.ZipFile(source) as archive:
                    data = archive.read("aircraft_gui.bank")
                    master = archive.read("masterbank.bank")
                    (pack / "_crew_dialogs_ground_ru.bank").write_bytes(data)
                    # Packs don't always use lower-case names.
                    (pack / "Masterbank.bank").write_bytes(master)
                voice = Scan(pack)
                buses, events = parse_bank(data)
                nested = nested_events([data, master])
                expected = {guid for guid, bus in events if guid not in nested and bus in buses}
                targets = [t for t in voice.targets if t.group == "voice_pack_ground"]
                self.assertEqual({uuid.UUID(t.guid).bytes_le for t in targets}, expected)
                # Without names, the masterbank voice buses are found by GUID.
                named_buses = {(t.group, t.offset) for t in scan.targets if t.bank == "masterbank.bank" and t.group in VOICE_BUSES.values()}
                self.assertEqual({(t.group, t.offset) for t in voice.targets if t.bank == "Masterbank.bank"}, named_buses)
                gains = dict.fromkeys(GROUPS, 100)
                gains["voice_pack_ground"] = 50
                result = export(voice, gains, base / "output")
                with zipfile.ZipFile(result["archive"]) as output:
                    patched = {b.offset: b.db for b in parse_bank(output.read("_crew_dialogs_ground_ru.bank"))[0].values()}
                for t in targets:
                    self.assertAlmostEqual(patched[t.offset], t.db - 6.0206, places=3)
                self.assertEqual(result["changed_fields"], len(targets))

    def test_event_nested_from_another_bank_is_skipped(self):
        # engine_cooldown lives in tanks_effects.bank, and events in tanks_engines.bank nest it.
        source = self.sample("RCSM")
        with PackageContext(source) as package:
            strings = string_table(package.metadata("masterbank.strings.bank"))
        guid = str(uuid.UUID(bytes_le=next(g for g, path in strings.items() if path == "event:/ground/effects/engine_cooldown")))
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory)
            with zipfile.ZipFile(source) as archive:
                (pack / "tanks_effects.bank").write_bytes(archive.read("tanks_effects.bank"))
                self.assertIn(guid, {t.guid for t in Scan(pack).targets})
                (pack / "tanks_engines.bank").write_bytes(archive.read("tanks_engines.bank"))
            self.assertNotIn(guid, {t.guid for t in Scan(pack).targets})

    def test_game_folder_exports_only_changed_banks(self):
        source = self.sample("RCSM")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            game = base / "War Thunder"
            sound = game / "sound"
            (game / "content").mkdir(parents=True)
            (game / "content" / "pkg_main.ver").write_text("2.59.0.78\n")
            (sound / "mod").mkdir(parents=True)
            names = ("masterbank.bank", "masterbank.assets.bank", "masterbank.strings.bank", "aircraft_common.bank", "aircraft_common.assets.bank")
            with zipfile.ZipFile(source) as archive:
                for name in names:
                    (sound / name).write_bytes(archive.read(name))
            # A mod already installed in sound/mod must not be read as part of the game.
            (sound / "mod" / "masterbank.strings.bank").write_bytes(b"mod")
            for path in (game, sound):
                scan = Scan(path)
                self.assertEqual(scan.game_version, "2.59.0.78")
                self.assertEqual(set(scan.files), set(names))
                self.assertTrue(any("sound/mod" in w for w in scan.warnings))
            gains = dict.fromkeys(GROUPS, 100)
            with self.assertRaisesRegex(ValueError, "没有调整"):
                export(scan, gains, base / "none")
            gains["aircraft_common"] = 50
            result = export(scan, gains, base / "one")
            self.assertTrue(Path(result["archive"]).name.startswith("WarThunder-2.59.0.78"))
            with zipfile.ZipFile(result["archive"]) as output:
                self.assertEqual(set(output.namelist()), {"aircraft_common.bank", "aircraft_common.assets.bank"})
                self.assertEqual(output.read("aircraft_common.assets.bank"), (sound / "aircraft_common.assets.bank").read_bytes())
            self.assertEqual(result["changed_fields"], scan.counts["aircraft_common"])
            gains["crew_ground"] = 80
            with zipfile.ZipFile(export(scan, gains, base / "two")["archive"]) as output:
                self.assertEqual(set(output.namelist()), set(names))

    def test_unknown_bank_version_rejected(self):
        with PackageContext(self.sources[0]) as package:
            data = bytearray(package.metadata("aircraft_guns.bank"))
        struct.pack_into("<I", data, 20, 0xFFFF)
        with self.assertRaises(FormatError):
            parse_bank(bytes(data))

    def test_every_category_alone_keeps_other_categories_out_of_patch_plan(self):
        for scan in self.scans:
            for category in GROUPS:
                gains = dict.fromkeys(GROUPS, 100)
                gains[category] = 50
                edits = [edit for bank in patches_for(scan, gains).values() for edit in bank]
                self.assertEqual(len(edits), scan.counts[category])
                self.assertTrue(all(edit["group"] == category for edit in edits))

    def test_directory_input_identity_and_stale_scan_rejected(self):
        source = self.sources[0]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            input_dir = base / "input"
            input_dir.mkdir()
            names = ("masterbank.bank", "masterbank.strings.bank", "aircraft_common.bank")
            with zipfile.ZipFile(source) as original:
                for name in names:
                    (input_dir / name).write_bytes(original.read(name))
            scan = Scan(input_dir)
            result = export(scan, dict.fromkeys(GROUPS, 100), base / "output")
            with zipfile.ZipFile(result["archive"]) as output:
                self.assertEqual(set(output.namelist()), set(names))
                for name in names:
                    self.assertEqual(output.read(name), (input_dir / name).read_bytes())
            changed = input_dir / "aircraft_common.bank"
            data = bytearray(changed.read_bytes())
            data[100] ^= 1
            changed.write_bytes(data)
            with self.assertRaisesRegex(FormatError, "已变化"):
                export(scan, dict.fromkeys(GROUPS, 100), base / "stale")
            self.assertEqual(list((base / "stale").iterdir()), [])


class PackageContext:
    def __init__(self, path):
        self.package = Package(path)

    def __enter__(self):
        return self.package

    def __exit__(self, *args):
        self.package.close()


def verify_export_bytes(source, result):
    """Compare every byte independently of the exporter's copy loop."""
    manifest = json.loads(Path(result["manifest"]).read_text())
    by_name = {item["path"]: item for item in manifest["files"]}
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(result["archive"]) as after:
        expected_names = {i.filename for i in before.infolist() if not i.is_dir()}
        assert set(after.namelist()) == expected_names
        for name in after.namelist():
            edits = manifest["patches"].get(name, [])
            offsets = {edit["offset"] + delta for edit in edits for delta in range(4)}
            original_hash, output_hash = hashlib.sha256(), hashlib.sha256()
            position = 0
            with before.open(name) as a, after.open(name) as b:
                while left := a.read(1024 * 1024):
                    right = b.read(len(left))
                    assert len(left) == len(right)
                    original_hash.update(left)
                    output_hash.update(right)
                    if left != right:
                        assert all(position + i in offsets for i, (x, y) in enumerate(zip(left, right)) if x != y), name
                    position += len(left)
                assert not b.read(1)
            assert original_hash.hexdigest() == by_name[name]["source_sha256"]
            assert output_hash.hexdigest() == by_name[name]["output_sha256"]
            if edits:
                data = after.read(name)
                for edit in edits:
                    assert struct.unpack_from("<f", data, edit["offset"])[0] == edit["new_db"]
    return {"files_verified": len(by_name), "fields_verified": result["changed_fields"], "all_other_bytes_identical": True}


if __name__ == "__main__":
    unittest.main()
