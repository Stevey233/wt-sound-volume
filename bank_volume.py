"""Offline volume edits for War Thunder FMOD Studio banks (file version 0x8e)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

__version__ = "0.1.0"
# The packaged program keeps its exports next to itself, and a source checkout keeps them in the checkout.
ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
OUTPUT_ROOT = ROOT / "exports"
SAMPLES = ROOT / "samples"
GROUP_INFO = {
    "aircraft_engine_own": ("引擎与履带", "自己飞机引擎", "外部视角、座舱、启动、熄火、加力和旋翼"),
    "aircraft_engine_other": ("引擎与履带", "其他飞机引擎", "其他飞机和直升机的引擎，包含敌我双方"),
    "ground_engine_own": ("引擎与履带", "自己地面引擎", "自己载具的车内、车外、启动和熄火"),
    "ground_engine_other": ("引擎与履带", "其他地面引擎", "普通 AI 路由，不包含专用敌方事件"),
    "ground_engine_enemy": ("引擎与履带", "敌方地面引擎", "专用 _enemies 事件"),
    "tracks_own": ("引擎与履带", "自己履带", "自己载具的车内和车外履带"),
    "tracks_other": ("引擎与履带", "其他载具履带", "普通 AI 路由的履带"),
    "tracks_enemy": ("引擎与履带", "敌方履带", "专用敌方履带事件"),
    "engine_misc": ("引擎与履带", "其他引擎目录事件", "引擎目录中不属于上述路由的事件，含地表和辅助声"),
    "naval_engines": ("引擎与履带", "舰船引擎", "naval/engines，只在游戏原版里有"),
    "missile": ("导弹与武器", "导弹持续飞行", "轻、中、重型 missile_fly，不包含发射、告警或爆炸"),
    "missile_launch": ("导弹与武器", "导弹发射", "missile_start，包含自己、其他载具和内部视角"),
    "rocket_fly": ("导弹与武器", "火箭弹持续飞行", "rocket_fly 事件"),
    "rocket_launch": ("导弹与武器", "火箭弹发射", "rocket_start 和 rocket_start_ai"),
    "aircraft_weapons": ("导弹与武器", "飞机机枪、机炮与其他武器", "飞机武器目录中除导弹和火箭弹以外的事件"),
    "ground_cannons": ("导弹与武器", "地面主炮与机炮", "ground/weapon/cannons"),
    "ground_mguns": ("导弹与武器", "地面机枪", "ground/weapon/mguns"),
    "ground_rockets": ("导弹与武器", "地面火箭弹", "ground/weapon/rockets"),
    "ground_weapons_misc": ("导弹与武器", "其他地面武器", "地面武器目录中的剩余事件"),
    "naval_weapons": ("导弹与武器", "舰炮与舰载武器", "naval/weapon，只在游戏原版里有"),
    "aircraft_explosions": ("爆炸与机械", "飞机爆炸", "aircraft/explosions"),
    "ground_explosions": ("爆炸与机械", "地面爆炸", "ground/explosions"),
    "naval_explosions": ("爆炸与机械", "舰船爆炸", "naval/explosions，只在游戏原版里有"),
    "aircraft_effects": ("爆炸与机械", "飞机机械与效果", "起落架、襟翼、舱盖、受击和其他飞机效果"),
    "ground_effects": ("爆炸与机械", "地面机械与效果", "炮塔、装填、悬挂、受击和其他地面效果"),
    "aircraft_common": ("爆炸与机械", "飞机通用声音", "振动、过热、漏液、投弹和炸弹呼啸等"),
    "object_crash": ("爆炸与机械", "物体碰撞与破坏", "ground/object_crash"),
    "modules_ground": ("爆炸与机械", "地面模块事件", "modules/ground，包含包内模块射击和弹壳声"),
    "naval_effects": ("爆炸与机械", "舰船效果与海上环境", "naval/effects 和 naval/ambient，只在游戏原版里有"),
    "rwr": ("环境与告警", "雷达与导弹告警", "雷达、导弹、扫描和发射探测告警，按 alarm 事件名分类"),
    "vws": ("环境与告警", "语音警告", "aircraft/gui/vws 目录"),
    "aircraft_gui": ("环境与告警", "界面、锁定与其他提示", "飞机 gui 目录中除 RWR、VWS 以外的事件"),
    "aircraft_ambient": ("环境与告警", "空中环境", "aircraft/ambient"),
    "ground_ambient": ("环境与告警", "地面环境", "ground/ambient"),
    "music": ("环境与告警", "音乐", "aircraft/music 和活动音乐"),
    "crew_ground": ("乘员与其他", "地面乘员语音", "masterbank 的混音总线，原版地面乘员语音也会变"),
    "crew_naval": ("乘员与其他", "海军乘员语音", "masterbank 的混音总线，原版海军乘员语音也会变"),
    "crew_common": ("乘员与其他", "通用乘员与通话点击", "共用混音总线，包含 radio_click 通话点击声"),
    "radio_chat": ("乘员与其他", "无线电语音", "masterbank 的 radio_chat 混音总线"),
    "voice_pack_ground": ("乘员与其他", "地面乘员语音事件", "crew_dialogs_ground bank 里的语音，和上面的总线叠加"),
    "voice_pack_naval": ("乘员与其他", "海军乘员语音事件", "crew_dialogs_naval bank 里的语音，和上面的总线叠加"),
    "voice_pack_common": ("乘员与其他", "通用乘员语音事件", "crew_dialogs_common bank 里的语音，和上面的总线叠加"),
    "misc": ("乘员与其他", "其他已命名声音", "未归入以上类别的独立声音事件"),
    "unnamed_bank": ("乘员与其他", "没有事件名的其他 bank", "包里没有 masterbank.strings.bank，这些 bank 只能整体调节"),
}
GROUPS = {key: info[1] for key, info in GROUP_INFO.items()}
VOICE_BUSES = {
    "bus:/dialogs/dialogs/crew_ground": "crew_ground",
    "bus:/dialogs/dialogs/crew_naval": "crew_naval",
    "bus:/dialogs/crew_common": "crew_common",
    "bus:/dialogs/dialogs/radio_chat": "radio_chat",
}
# Gaijin's mixer uses these voice bus GUIDs. RCSM and OPEX share them, so a pack
# without a strings table can still find the buses in its masterbank.bank.
VOICE_BUS_GUIDS = {
    uuid.UUID("de263ae6-8db1-4c80-a13c-9d4ea36cbacf").bytes_le: "bus:/dialogs/dialogs/crew_ground",
    uuid.UUID("4a52afc2-fbf1-4bb9-b055-379a2acd4e4b").bytes_le: "bus:/dialogs/dialogs/crew_naval",
    uuid.UUID("51dca951-e1c2-4de2-8b33-cd9c60eaaf2a").bytes_le: "bus:/dialogs/crew_common",
    uuid.UUID("4d2d2429-e5e0-47c0-9e15-a7434a93d1c4").bytes_le: "bus:/dialogs/dialogs/radio_chat",
}
CREW_BANKS = {"ground": "voice_pack_ground", "naval": "voice_pack_naval", "common": "voice_pack_common"}
MISSILES = {
    f"event:/aircraft/weapon/missile_{size}_fly" for size in ("light", "med", "heavy")
}
MAX_METADATA = 64 * 1024 * 1024


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data: bytes, start: int = 0, end: int | None = None):
        self.data = data
        self.pos = start
        self.end = len(data) if end is None else end

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > self.end:
            raise FormatError(f"数据截断，位置 0x{self.pos:x}")
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def integer(self, size: int) -> int:
        return int.from_bytes(self.take(size), "little")

    def x16(self) -> int:
        low = self.integer(2)
        return (low & 0x7FFF) | (self.integer(2) << 15) if low & 0x8000 else low

    def array(self, width: int) -> list[bytes]:
        count = self.x16() >> 1
        if not count:
            return []
        if self.integer(2) != width or count > (self.end - self.pos) // width:
            raise FormatError("数组宽度或长度无效")
        return [self.take(width) for _ in range(count)]

    def indices(self) -> list[int]:
        count = self.x16()
        if count > (self.end - self.pos) // 3:
            raise FormatError("字符串索引长度无效")
        return [self.integer(3) for _ in range(count)]


def chunks(data: bytes, start: int, end: int, depth: int = 0):
    if depth > 16:
        raise FormatError("bank 嵌套层数过多")
    while start < end:
        if data[start] == 0:
            start += 1
        if start == end:
            break
        if start + 8 > end:
            raise FormatError(f"chunk 头截断，位置 0x{start:x}")
        tag = data[start:start + 4]
        size = struct.unpack_from("<I", data, start + 4)[0]
        payload = start + 8
        if not all(32 <= c < 127 for c in tag) or payload + size > end:
            raise FormatError(f"chunk 范围无效，位置 0x{start:x}")
        yield tag, payload, size, depth
        if tag == b"LIST":
            if size < 4:
                raise FormatError("LIST 缺少类型")
            yield from chunks(data, payload + 4, payload + size, depth + 1)
        start = payload + size


def read_metadata(stream, size: int) -> bytes:
    header = stream.read(12)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"FEV ":
        raise FormatError("不是 FMOD RIFF/FEV bank")
    if struct.unpack_from("<I", header, 4)[0] + 8 != size:
        raise FormatError("RIFF 文件长度不匹配")
    output = bytearray(header)
    while len(output) < size:
        chunk = stream.read(8)
        if len(chunk) != 8:
            raise FormatError("bank 头截断")
        length = struct.unpack_from("<I", chunk, 4)[0]
        if len(output) + 8 + length > min(size, MAX_METADATA):
            raise FormatError("bank 控制数据过大或长度无效")
        payload = stream.read(length)
        if len(payload) != length:
            raise FormatError("bank 控制数据截断")
        output.extend(chunk)
        output.extend(payload)
        if chunk[:4] == b"LIST" and payload[:4] == b"PROJ":
            return bytes(output)
        if chunk[:4] != b"FMT ":
            raise FormatError("不支持的 bank 顶层布局")
    raise FormatError("找不到 PROJ 控制数据")


def string_table(data: bytes) -> dict[bytes, str]:
    tables = [(p, n) for tag, p, n, _ in chunks(data, 12, len(data)) if tag == b"STDT"]
    if len(tables) != 1:
        raise FormatError("需要且只支持一个 STDT 字符串表")
    p, n = tables[0]
    r = Reader(data, p, p + n)
    if r.integer(4) != 1:
        raise FormatError("只支持 24 位 radix 字符串表")
    nodes, guids = r.array(8), r.array(16)
    blob = r.take(r.x16())
    leaves, parents = r.indices(), r.indices()
    if len(leaves) != len(guids) or len(parents) != len(nodes):
        raise FormatError("字符串表索引数量不匹配")
    result = {}
    for guid, leaf in zip(guids, leaves):
        segments = []
        seen = set()
        while leaf != 0xFFFFFF:
            if leaf >= len(nodes) or leaf in seen or len(seen) > 256:
                raise FormatError("字符串表包含循环或越界索引")
            seen.add(leaf)
            offset = int.from_bytes(nodes[leaf][:4], "little") & 0xFFFFFF
            if offset != 0xFFFFFF:
                end = blob.find(b"\0", offset)
                if offset >= len(blob) or end < 0:
                    raise FormatError("字符串缺少结尾")
                segments.append(blob[offset:end].decode("utf-8"))
            leaf = parents[leaf]
        if guid in result:
            raise FormatError("字符串表含重复 GUID")
        result[guid] = "".join(reversed(segments))
    return result


@dataclass(frozen=True)
class Bus:
    guid: bytes
    parent: bytes
    offset: int
    db: float
    effects: bool


@dataclass(frozen=True)
class Target:
    bank: str
    event: str
    guid: str
    group: str
    route: str
    offset: int
    db: float


def parse_bank(data: bytes):
    records = list(chunks(data, 12, len(data)))
    versions = [struct.unpack_from("<II", data, p) for t, p, n, _ in records if t == b"FMT " and n == 8]
    if versions != [(0x8E, 0x8C)]:
        raise FormatError(f"不支持的 FMOD bank 版本 {versions}，当前支持 0x8e/0x8c")
    buses, events = {}, []
    owner = None
    for tag, p, n, depth in records:
        if tag in (b"IBSB", b"GBSB", b"RBSB", b"MBSB"):
            if n < 16:
                raise FormatError("总线 GUID 截断")
            guid = data[p:p + 16]
            parent = b""
            if tag != b"MBSB":
                if n < 42 or struct.unpack_from("<H", data, p + 16)[0] != 24:
                    raise FormatError("不支持的总线路由布局")
                parent = data[p + 18:p + 34]
            owner = (guid, parent, depth)
        elif tag == b"BUS " and owner is not None:
            guid, parent, owner_depth = owner
            if owner_depth != depth or guid in buses:
                raise FormatError("总线归属不明确")
            r = Reader(data, p, p + n)
            r.take(8)
            effects = bool(r.array(16) + r.array(16))
            if r.integer(2) != 8:
                raise FormatError("不支持的混音音量结构")
            offset = r.pos
            db, pitch = struct.unpack("<ff", r.take(8))
            if not math.isfinite(db) or not -200 <= db <= 100 or not math.isfinite(pitch):
                raise FormatError("混音音量不是有效分贝值")
            buses[guid] = Bus(guid, parent, offset, db, effects)
            owner = None
        elif tag == b"EVTB":
            if n < 80:
                raise FormatError("事件结构截断")
            events.append((data[p:p + 16], data[p + 48:p + 64]))
    return buses, events


def classify(event: str, route: str) -> str | None:
    if not event.startswith("event:"):
        return None
    if voice_group(route) is not None:
        return None
    # Infantry mode is out of scope, so its events stay unchanged.
    if event.startswith("event:/infantry/"):
        return None
    if event.startswith("event:/naval/"):
        part = event.split("/")[2]
        return {"engines": "naval_engines", "weapon": "naval_weapons", "explosions": "naval_explosions"}.get(part, "naval_effects")
    if event.startswith(("event:/aircraft/music/", "event:/event/music/")):
        return "music"
    if event in MISSILES:
        return "missile"
    if event.startswith("event:/aircraft/gui/") and event.rsplit("/", 1)[1] in {
        "alarm_radar", "alarm_rocket", "alarm_con_scan", "alarm_spin_scan", "alarm_launch_detected", "alarm_heatseeker_scan",
    }:
        return "rwr"
    if event.startswith(("event:/aircraft/engines/", "event:/ground/engines/", "event:/naval/engines/")):
        enemy = "/_enemies/" in event or route.startswith("bus:/sounds_tank_enemy_engines/") or "_enemies" in route
        other = "/engines_ai" in route
        if "/tracks" in event or "/tracks" in route:
            return "tracks_enemy" if enemy else "tracks_other" if other else "tracks_own"
        if "/engines" not in route:
            return "engine_misc"
        if event.startswith("event:/aircraft/engines/"):
            return "aircraft_engine_other" if other else "aircraft_engine_own"
        if event.startswith("event:/ground/engines/"):
            return "ground_engine_enemy" if enemy else "ground_engine_other" if other else "ground_engine_own"
        return "engine_misc"
    if event.startswith("event:/aircraft/weapon/"):
        name = event.rsplit("/", 1)[1]
        if name.startswith("missile_") and "start" in name:
            return "missile_launch"
        if name == "rocket_fly":
            return "rocket_fly"
        if name.startswith("rocket_start"):
            return "rocket_launch"
        return "aircraft_weapons"
    prefixes = {
        "event:/ground/weapon/cannons/": "ground_cannons",
        "event:/ground/weapon/mguns/": "ground_mguns",
        "event:/ground/weapon/rockets/": "ground_rockets",
        "event:/ground/weapon/": "ground_weapons_misc",
        "event:/aircraft/explosions/": "aircraft_explosions",
        "event:/ground/explosions/": "ground_explosions",
        "event:/aircraft/effects/": "aircraft_effects",
        "event:/ground/effects/": "ground_effects",
        "event:/aircraft/common/": "aircraft_common",
        "event:/ground/object_crash/": "object_crash",
        "event:/modules/ground/": "modules_ground",
        "event:/aircraft/gui/rwr/": "rwr",
        "event:/aircraft/gui/vws/": "vws",
        "event:/aircraft/gui/": "aircraft_gui",
        "event:/aircraft/ambient/": "aircraft_ambient",
        "event:/ground/ambient/": "ground_ambient",
    }
    for prefix, group in prefixes.items():
        if event.startswith(prefix):
            return group
    # Voice events use the shared voice buses, so their gain is applied once.
    if event.startswith(("event:/dialogs_", "event:/dialogs/")):
        return None
    return "misc"


def voice_group(route: str) -> str | None:
    return next((group for bus, group in VOICE_BUSES.items() if route == bus or route.startswith(bus + "/")), None)


def game_sound_dir(path):
    """Return the sound folder and build of a game install, or None.

    path may be the install folder or its sound folder. An install has
    content/pkg_main.ver next to sound/masterbank.strings.bank.
    """
    path = Path(path).expanduser()
    for root in (path, path.parent):
        version = root / "content" / "pkg_main.ver"
        sound = root / "sound"
        if path in (root, sound) and version.is_file() and (sound / "masterbank.strings.bank").is_file():
            return sound, version.read_text(encoding="utf-8", errors="replace").strip()
    return None


def find_game_installs():
    """Return install folders found in the usual places, for the folder dialog and the start page."""
    home = Path.home()
    steam_roots = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam", home / ".local/share/Steam", home / ".steam/steam"]
    # WT_GAME_DIR names an install that isn't in a usual place.
    candidates = [Path(os.environ["WT_GAME_DIR"])] if os.environ.get("WT_GAME_DIR") else []
    candidates += [steam / "steamapps/common/War Thunder" for steam in steam_roots]
    candidates.append(Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "WarThunder")
    # Games installed in other Steam libraries, such as D:\SteamLibrary, are listed in libraryfolders.vdf.
    for steam in steam_roots:
        try:
            text = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for library in re.findall(r'"path"\s+"([^"]+)"', text):
            candidates.append(Path(library.replace("\\\\", "\\")) / "steamapps" / "common" / "War Thunder")
    found = {}
    for path in candidates:
        try:
            if game_sound_dir(path):
                found.setdefault(path.resolve(), path)
        except OSError:
            continue
    return list(found.values())


def is_metadata_bank(name):
    """Return whether a file holds FMOD events and mixer data rather than only audio."""
    lower = name.lower()
    return lower.endswith(".bank") and not lower.endswith((".assets.bank", ".streams.bank", ".strings.bank"))


def crew_group(name):
    """Map a crew voice bank such as _crew_dialogs_ground_ru.bank to its category."""
    match = re.search(r"crew_dialogs?_(ground|naval|common)", name.lower())
    return CREW_BANKS[match.group(1)] if match else None


def nested_events(banks):
    """Return the event GUIDs that some event plays as a nested instrument.

    banks holds the metadata of every bank in the pack, because a parent event
    can nest an event from another bank. The EVIB chunks of the sample packs
    total about 100 KB, so every 16-byte window fits in a set.
    """
    windows = set()
    guids = set()
    for data in banks:
        guids.update(guid for guid, _ in parse_bank(data)[1])
        for tag, p, n, _ in chunks(data, 12, len(data)):
            if tag == b"EVIB":
                windows.update(data[i:i + 16] for i in range(p, p + n - 15))
    return guids & windows


def missing_strings_reason(files, names, archive):
    """Explain why the input isn't one pack that the scanner can read."""
    action = "请解压后点“选择目录”" if archive else "请点“选择目录”"
    if names:
        folders = "、".join(str(PurePosixPath(n).parent) for n in sorted(names))
        return f"包里有 {len(names)} 套音效，分别在 {folders}。{action}，选中要用的那一套所在的文件夹"
    banks = [n for n in files if n.lower().endswith(".bank")]
    if not banks:
        return "没有找到 FMOD 的 .bank 文件，这不像战争雷霆音效包"
    metadata = [n for n in banks if is_metadata_bank(n)]
    if not metadata:
        return (f"这个包只有 {len(banks)} 个 .assets.bank 音频文件，缺少同名的 .bank 文件。"
                "音量数据在 .bank 里，语音包一般把两种文件成对提供，请连同 .bank 一起选择")
    folders = "、".join(sorted({str(PurePosixPath(n).parent) for n in metadata}))
    return f"包里没有 masterbank.strings.bank，bank 文件又分散在 {folders}。{action}，选中要用的那个文件夹"


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or "\\" in name or "\0" in name or path.is_absolute() or any(p in (".", "..") or ":" in p for p in name.split("/")):
        raise FormatError(f"包内路径不安全 {name!r}")
    return name


class Package:
    def __init__(self, path: str | Path, top_level: bool = False):
        """Open a ZIP or a directory. top_level reads only the files directly in a directory."""
        self.path = Path(path).expanduser().resolve(strict=True)
        self.archive = None
        self.files = {}
        if self.path.is_file():
            with self.path.open("rb") as stream:
                magic = stream.read(8)
            for signature, kind in ((b"Rar!\x1a\x07", "RAR"), (b"7z\xbc\xaf\x27\x1c", "7z")):
                if magic.startswith(signature):
                    raise FormatError(f"这是 {kind} 压缩包，工具只能直接读取 ZIP。请先解压，再点“选择目录”选中解压出的文件夹")
            if not zipfile.is_zipfile(self.path):
                raise FormatError("这个文件不是 ZIP 压缩包。请选择音效包 ZIP，或者解压后的目录")
            self.archive = zipfile.ZipFile(self.path)
            try:
                for info in self.archive.infolist():
                    # Windows zipfile turns backslashes into slashes, so check the stored name.
                    safe_name(info.orig_filename)
                    if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                        raise FormatError("不支持符号链接或加密的 ZIP 成员")
                    if not info.is_dir():
                        if info.filename in self.files:
                            raise FormatError("ZIP 含重复文件路径")
                        self.files[info.filename] = info.file_size
            except Exception:
                self.archive.close()
                raise
        elif self.path.is_dir() and top_level:
            # The game's sound folder holds mod/ and may link it elsewhere, so skip folders and links.
            for p in self.path.iterdir():
                if p.is_file() and not p.is_symlink():
                    self.files[safe_name(p.name)] = p.stat().st_size
        elif self.path.is_dir():
            for p in self.path.rglob("*"):
                if p.is_symlink() or getattr(p, "is_junction", lambda: False)():
                    raise FormatError("输入目录不能包含符号链接")
                if p.is_file():
                    self.files[safe_name(p.relative_to(self.path).as_posix())] = p.stat().st_size
        else:
            raise FormatError("请选择 ZIP 文件或解压后的目录")
        if len(self.files) > 10000 or sum(self.files.values()) > 16 * 1024**3:
            self.close()
            raise FormatError("输入超过 10000 个文件或 16 GiB")

    def close(self):
        if self.archive:
            self.archive.close()

    @contextmanager
    def open(self, name):
        if self.archive:
            with self.archive.open(name) as stream:
                yield stream
        else:
            path = self.path / name
            if path.resolve() != path or path.is_symlink():
                raise FormatError("输入文件路径发生变化")
            with path.open("rb") as stream:
                yield stream

    def metadata(self, name):
        with self.open(name) as stream:
            return read_metadata(stream, self.files[name])


class Scan:
    def __init__(self, source: str | Path):
        game = game_sound_dir(source) if Path(source).expanduser().is_dir() else None
        self.game_version = game[1] if game else None
        package = Package(game[0], top_level=True) if game else Package(source)
        self.source = str(package.path)
        self.targets = []
        self.metadata_hashes = {}
        self.warnings = []
        self.unnamed = 0
        self.nested = 0
        self.snapshots = 0
        self.unpatchable = []
        self.shared_events = []
        try:
            names = [n for n in package.files if PurePosixPath(n).name.lower() == "masterbank.strings.bank"]
            banks = [n for n in package.files if is_metadata_bank(n)]
            folders = {PurePosixPath(n).parent for n in banks}
            if len(names) > 1 or (not names and len(folders) != 1):
                raise FormatError(missing_strings_reason(package.files, names, package.archive is not None))
            if names:
                folder = PurePosixPath(names[0]).parent
                data = package.metadata(names[0])
                parse_bank(data)
                strings = string_table(data)
                self.metadata_hashes[names[0]] = hashlib.sha256(data).hexdigest()
            else:
                folder = folders.pop()
                strings = {}
                self.warnings.append("包里没有 masterbank.strings.bank，事件没有名字，只能按 bank 整体调节。")
            self.has_strings = bool(names)
            prefix = "" if str(folder) == "." else str(folder) + "/"
            metadata = {name: package.metadata(name) for name in sorted(package.files)
                        if PurePosixPath(name).parent == folder and is_metadata_bank(name)}
            nested = nested_events(metadata.values())
            for name, data in metadata.items():
                buses, events = parse_bank(data)
                self.metadata_hashes[name] = hashlib.sha256(data).hexdigest()
                base = PurePosixPath(name).name.lower()
                if base == "masterbank.bank":
                    for guid, bus in buses.items():
                        route = strings.get(guid) or VOICE_BUS_GUIDS.get(guid, "")
                        if route in VOICE_BUSES:
                            self.targets.append(Target(name, route, str(uuid.UUID(bytes_le=guid)), VOICE_BUSES[route], route, bus.offset, bus.db))
                    if not strings:
                        continue
                whole_bank = crew_group(base) or (None if strings else "unnamed_bank")
                if whole_bank:
                    self.add_top_level_events(name, buses, events, nested, strings, whole_bank)
                    continue
                for guid, input_guid in events:
                    event = strings.get(guid, "")
                    if not event:
                        self.unnamed += 1
                        continue
                    if event.startswith("snapshot:"):
                        self.snapshots += 1
                        continue
                    bus = buses.get(input_guid)
                    if not bus:
                        self.unpatchable.append(event)
                        continue
                    route = strings.get(bus.parent, "")
                    shared_group = voice_group(route)
                    if shared_group is not None:
                        self.shared_events.append({"event": event, "bank": name, "group": shared_group, "route": route})
                        continue
                    group = classify(event, route)
                    if not group:
                        continue
                    if bus.effects:
                        self.unpatchable.append(event)
                        continue
                    self.targets.append(Target(name, event, str(uuid.UUID(bytes_le=guid)), group, route, bus.offset, bus.db))
            if not self.targets:
                raise FormatError("没有找到可调节的声音事件")
            keys = [(t.bank, t.offset) for t in self.targets]
            if len(keys) != len(set(keys)):
                raise FormatError("多个事件共用输入总线，不能独立修改")
            self.counts = {key: sum(t.group == key for t in self.targets) for key in GROUPS}
            if self.unpatchable:
                self.warnings.append(f"{len(self.unpatchable)} 个事件没有可安全修改的输入总线，已跳过。")
            mod = package.path / "mod"
            if game and mod.is_dir() and any(mod.iterdir()):
                self.warnings.append("游戏的 sound/mod 里已经有文件，导出的 mod 会和它们混在一起。")
            found_missiles = {t.event for t in self.targets if t.group == "missile"}
            if found_missiles and found_missiles != MISSILES:
                self.warnings.append("包内导弹持续声不完整，只能调节检测到的事件。")
            self.files = dict(package.files)
            self.prefix = prefix
        finally:
            package.close()

    def add_top_level_events(self, name, buses, events, nested, strings, group):
        """Add every event of a bank that the game starts directly.

        Without names, a nested event can't be told apart by its path. Its parent
        event lists it in an EVIB chunk, and the parent's input bus already
        carries the gain, so nested events are skipped. Snapshots have no input bus.
        """
        for guid, input_guid in events:
            if guid in nested:
                self.nested += 1
                continue
            bus = buses.get(input_guid)
            if not bus:
                self.snapshots += 1
                continue
            label = strings.get(guid) or f"{PurePosixPath(name).name} 中的事件"
            if bus.effects:
                self.unpatchable.append(label)
                continue
            route = strings.get(bus.parent) or VOICE_BUS_GUIDS.get(bus.parent, "")
            self.targets.append(Target(name, label, str(uuid.UUID(bytes_le=guid)), group, route, bus.offset, bus.db))

    def summary(self):
        return {"source": self.source, "game_version": self.game_version, "strings_table": self.has_strings, "counts": self.counts, "files": len(self.files), "bytes": sum(self.files.values()),
                "banks": sorted({t.bank for t in self.targets}), "warnings": self.warnings,
                "unnamed_events_skipped": self.unnamed, "nested_events_skipped": self.nested, "snapshot_records_skipped": self.snapshots,
                "unpatchable_events": self.unpatchable, "events_controlled_by_shared_bus": self.shared_events}


def export_names(scan, patches):
    """Pick the files to export. A pack is exported whole. From the game only the
    changed banks are exported, with their sample banks so the pair stays together."""
    if not scan.game_version:
        return sorted(scan.files)
    names = set()
    for bank in patches:
        stem = bank[:-len(".bank")]
        names.update(n for n in (bank, stem + ".assets.bank", stem + ".streams.bank") if n in scan.files)
        if bank.lower() == "masterbank.bank":
            names.update(n for n in scan.files if n.lower() == "masterbank.strings.bank")
    if not names:
        raise ValueError("没有调整任何类别，不需要导出")
    return sorted(names)


def gains_checked(gains):
    if set(gains) != set(GROUPS):
        raise ValueError("音量参数不完整")
    result = {}
    for key, value in gains.items():
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 400:
            raise ValueError("音量范围为 0 到 400%")
        result[key] = value
    return result


def patches_for(scan, gains):
    gains = gains_checked(gains)
    patches = {}
    for t in scan.targets:
        percent = gains[t.group]
        if percent == 100:
            continue
        db = min(t.db, -80.0) if percent == 0 else max(-200.0, min(100.0, t.db + 20 * math.log10(percent / 100)))
        packed = struct.pack("<f", db)
        if packed == struct.pack("<f", t.db):
            continue
        patches.setdefault(t.bank, []).append({**t.__dict__, "new_db": struct.unpack("<f", packed)[0], "percent": percent})
    return patches


def export(scan: Scan, gains: dict, output_root: Path = OUTPUT_ROOT, progress=lambda message: None):
    gains = gains_checked(gains)
    for group, value in gains.items():
        if value != 100 and not scan.counts[group]:
            raise ValueError(f"包内未找到{GROUPS[group]}，无法应用该音量")
    patches = patches_for(scan, gains)
    output_root = Path(output_root).expanduser().resolve()
    source = Path(scan.source)
    if source.is_dir() and (output_root == source or source in output_root.parents):
        raise ValueError("输出目录不能位于输入目录中")
    output_root.mkdir(parents=True, exist_ok=True)
    names = export_names(scan, patches)
    if shutil.disk_usage(output_root).free < sum(scan.files[n] for n in names) + 64 * 1024**2:
        raise ValueError("输出目录可用空间不足")
    stage = Path(tempfile.mkdtemp(prefix=".export-", dir=output_root))
    package = None
    try:
        package = Package(source, top_level=bool(scan.game_version))
        if package.files != scan.files:
            raise FormatError("源文件列表或大小已变化，请重新扫描")
        for name, expected in scan.metadata_hashes.items():
            if hashlib.sha256(package.metadata(name)).hexdigest() != expected:
                raise FormatError("源 bank 已变化，请重新扫描")
        if scan.game_version:
            archive_path = stage / ("WarThunder-" + re.sub(r"[^\w.+-]", "_", scan.game_version)[:40] + "-sound-mod.zip")
        else:
            stem = re.sub(r"[^\w.+-]", "_", source.stem, flags=re.UNICODE)[:80] or "sound-mod"
            archive_path = stage / (stem + "-adjusted.zip")
        kind = "game resource, the game's own sound banks" if scan.game_version else "game resource, user supplied sound mod"
        manifest = {"format": 1, "source_kind": kind, "source": scan.source, "game_version": scan.game_version,
                    "fmod_file_version": "0x8e", "fmod_compat_version": "0x8c", "gains_percent": gains,
                    "strings_table": scan.has_strings, "nested_events_skipped": scan.nested,
                    "counts": scan.counts, "patches": patches, "files": [],
                    "events_controlled_by_shared_bus": scan.shared_events,
                    "validation": "Offline metadata and byte-range verification only. Game playback has not been tested."}
        with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as dest:
            for index, name in enumerate(names):
                progress(f"正在导出 {index + 1}/{len(names)}  {name}")
                original_hash, changed_hash = hashlib.sha256(), hashlib.sha256()
                replacements = sorted(patches.get(name, []), key=lambda item: item["offset"])
                pos = 0
                pending = 0
                # Four-byte edits may cross a copy buffer boundary.
                with package.open(name) as src, dest.open(name, "w", force_zip64=True) as dst:
                    for patch in replacements:
                        remaining = patch["offset"] - pos
                        while remaining:
                            block = src.read(min(1024 * 1024, remaining))
                            if not block:
                                raise FormatError("源文件在导出时截断")
                            original_hash.update(block)
                            changed_hash.update(block)
                            dst.write(block)
                            pos += len(block)
                            remaining -= len(block)
                        before = src.read(4)
                        if before != struct.pack("<f", patch["db"]):
                            raise FormatError("源音量字段已变化，请重新扫描")
                        after = struct.pack("<f", patch["new_db"])
                        original_hash.update(before)
                        changed_hash.update(after)
                        dst.write(after)
                        pos += 4
                        pending += 1
                    while block := src.read(1024 * 1024):
                        original_hash.update(block)
                        changed_hash.update(block)
                        dst.write(block)
                        pos += len(block)
                if pos != package.files[name]:
                    raise FormatError("源文件在导出时改变大小")
                manifest["files"].append({"path": name, "size": pos, "source_sha256": original_hash.hexdigest(),
                                          "output_sha256": changed_hash.hexdigest(), "fields_changed": pending})
        progress("正在校验导出 ZIP 和音量字段")
        expected_files = {entry["path"]: entry for entry in manifest["files"]}
        with zipfile.ZipFile(archive_path) as check:
            for name in check.namelist():
                digest = hashlib.sha256()
                with check.open(name) as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                if digest.hexdigest() != expected_files[name]["output_sha256"]:
                    raise FormatError("导出校验失败")
            for name, edits in patches.items():
                with check.open(name) as stream:
                    data = read_metadata(stream, check.getinfo(name).file_size)
                buses, _ = parse_bank(data)
                actual = {b.offset: b.db for b in buses.values()}
                if any(actual.get(edit["offset"]) != edit["new_db"] for edit in edits):
                    raise FormatError("导出音量字段校验失败")
        manifest_path = stage / "volume-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        final = output_root / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        for attempt in range(20):
            try:
                stage.rename(final)
                break
            except PermissionError:
                # Windows virus scanners can hold the new ZIP open for a moment.
                if sys.platform != "win32" or attempt == 19:
                    raise
                time.sleep(0.25)
        return {"directory": str(final), "archive": str(final / archive_path.name),
                "manifest": str(final / manifest_path.name), "changed_fields": sum(map(len, patches.values()))}
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        if package:
            package.close()


def main():
    parser = argparse.ArgumentParser(description="战争雷霆音效包音量工具，原包只读")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="扫描 ZIP 或解压目录")
    inspect.add_argument("source")
    inspect.add_argument("--events", action="store_true", help="列出每个匹配事件")
    build = sub.add_parser("export", help="导出完整新 ZIP 和校验记录")
    build.add_argument("source")
    build.add_argument("--gain", action="append", default=[], metavar="CATEGORY=PERCENT", help="可重复设置，类别见 inspect 输出")
    build.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        scan = Scan(args.source)
        if args.command == "inspect":
            result = scan.summary()
            if args.events:
                result["events"] = [t.__dict__ for t in scan.targets]
        else:
            gains = dict.fromkeys(GROUPS, 100)
            for setting in args.gain:
                key, value = setting.split("=", 1)
                if key not in gains:
                    raise ValueError(f"未知类别 {key}")
                gains[key] = float(value)
            result = export(scan, gains, args.output_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        parser.exit(2, f"错误：{exc}\n")


if __name__ == "__main__":
    main()
