# 战争雷霆音效音量工具

调节《战争雷霆》音效的音量：第三方音效包、乘员语音包，或者游戏原版音效。程序按类别改 FMOD bank 里的音量字段，导出一个新的 ZIP，输入文件只读。

A desktop tool that changes the volume of War Thunder sounds by category. It edits the volume fields in FMOD Studio banks of a sound mod, a crew voice pack or the game itself, and exports a new ZIP. The input is never modified. The interface is in Chinese.

## 下载

在 [Releases](https://github.com/Stevey233/wt-sound-volume/releases) 下载对应系统的单文件程序，不需要安装 Python。

- Windows：`wt-sound-volume-windows-x64.exe`
- Linux：`wt-sound-volume-linux-x64`

程序没有代码签名。Windows 第一次运行下载的 exe 时，SmartScreen 可能拦截，点“更多信息”，再点“仍要运行”。程序会在自己旁边建一个 `exports` 文件夹存放导出结果，所以要放在有写入权限的目录里，不要放进 `C:\Program Files`。

## 能做什么

- 第三方音效包。直接打开 ZIP 或解压后的目录，比如 RCSM 和 OPEX。
- 乘员语音包。社区语音包一般成对提供 `_crew_dialogs_ground_ru.bank` 和 `.assets.bank` 这样的文件，没有字符串表，工具按 bank 整体调节。
- 游戏原版音效。点“游戏目录”选战争雷霆的安装目录，导出一个只含改动 bank 的 mod 包。

程序有 44 个调节项，分成五页，扫描后只显示包里有的类别。

- 引擎与履带：自己和其他飞机、自己、其他和敌方地面载具、三种履带、其他引擎事件、舰船引擎。
- 导弹与武器：导弹持续飞行、导弹发射、火箭弹飞行和发射、飞机机枪机炮、地面主炮、机枪、火箭弹、其他地面武器、舰炮。
- 爆炸与机械：飞机和地面爆炸、飞机和地面机械效果、飞机通用声音、物体碰撞、地面模块、舰船爆炸、舰船效果。
- 环境与告警：雷达和导弹告警、VWS 语音警告、界面提示、空中和地面环境、音乐。
- 乘员与其他：masterbank 里的四条语音总线（地面乘员、海军乘员、通用乘员和通话点击、无线电），三类乘员语音事件，其他声音。

其他飞机的引擎事件是敌我共用的，没法只调敌机。敌方地面载具有专用事件，可以单独调。

## 使用

1. 选择 ZIP、解压后的目录或游戏目录。选择后自动扫描。
2. 调整滑块。滑块中间是 100%，左半边是 0% 到 100%，右半边是 100% 到 400%。点击会跳到点击的位置，双击恢复 100%。选中滑块后，方向键每次调 1%，按住 Shift 每次调 10%。
3. 改过的类别左边有色条，压低是橙色，放大是绿色。每页顶部可以把本页所有类别设成同一个百分比。
4. 点“导出”。可以保存和读取 JSON 预设，也可以搜索事件清单。

## 安装到游戏

1. 把导出 ZIP 里的文件解压到游戏目录的 `sound/mod/`。
2. 在游戏目录的 `config.blk` 里，`sound{}` 块中加一行 `enable_mod:b=yes`。
3. 重启游戏。

想恢复原样，删掉 `sound/mod/` 里这些文件即可。以上步骤来自 [Gaijin wiki 的 Sound modifications](https://wiki.warthunder.com/Sound_modifications) 和 [2.57.0.32 更新公告](https://forum.warthunder.com/t/update-2-57-0-32-sound-mods-available/338311)。

从游戏原版导出的 bank 属于扫描时的游戏版本，`volume-manifest.json` 记录了版本号。游戏更新后，`sound/mod` 里的旧 bank 仍会盖住新版本的同名文件，所以每次更新后都要删掉它们，重新扫描、导出。

## 百分比的含义

100% 保持原值。其他百分比按 `原始 dB + 20 * log10(百分比 / 100)` 计算，50% 约为 -6.02 dB，200% 约为 +6.02 dB。0% 把音量字段降到 -80 dB。这个百分比是增益，不是主观响度。混响、游戏参数和快照还会参与最终混音，0% 可能有残留，放大可能失真。

## 支持的文件

工具读取 FMOD 文件版本 `0x8e`、兼容版本 `0x8c` 的 bank，按包里有没有 `masterbank.strings.bank` 分两种方式扫描。

- 有字符串表时，每个事件都有名字，工具按名字分类。乘员和无线电语音通过 masterbank 里的四条混音总线调节，这也会影响原版语音。
- 没有字符串表时，事件没有名字。文件名含 `crew_dialogs_ground`、`crew_dialogs_naval` 或 `crew_dialogs_common` 的 bank 进入对应的乘员语音类别，其他 bank 整体调节。masterbank 里的四条语音总线按 GUID 查找。
- 游戏原版模式只读 `sound/` 顶层的文件，不读 `sound/mod`。导出的 mod 包只含改过的 bank，以及同名的 `.assets.bank` 和 `.streams.bank`，改了 masterbank 时还带上 `masterbank.strings.bank`。步兵模式的事件不处理。

不支持的输入会给出原因：只有 `.assets.bank` 音频没有同名 `.bank` 的包，RAR 和 7z（先解压），一个包里有几套音效，其他 FMOD 版本。

程序启动时会在这些位置找游戏：环境变量 `WT_GAME_DIR`，Windows 的 Steam 和 `%LOCALAPPDATA%\WarThunder`，Linux 的 Steam，以及 Steam `libraryfolders.vdf` 列出的其他库。

## 工作原理

每个声音事件有一个输入总线，总线里有一个 float32 分贝音量字段。工具读字符串表，把事件 GUID 对应到输入总线，再定位这个字段。导出时流式复制文件，只改选中的 4 字节字段，然后重新读取 ZIP，核对每个文件的 SHA-256 和改过的字段。`volume-manifest.json` 记录源文件和输出文件的哈希、百分比、事件 GUID、字段偏移，以及修改前后的 dB。音频样本、GUID、路由和距离曲线都不动。

快照和未命名事件保持原样。未命名事件几乎都是嵌套事件，改它们会和上层事件叠加。没有事件名时，工具用 `EVIB` 块区分：上层事件在 `EVIB` 里引用它嵌套的事件，被引用的事件跳过。上层事件可能在另一个 bank 里，所以工具先收集包里所有 bank 的引用。在 RCSM 和 OPEX 两个包里，有名字的非快照事件只有 11/3747 和 15/3741 个被引用，没有名字的事件有 478/499 和 534/535 个被引用。

## 验证情况

- 用 RCSM（2026-09-07 版）、OPEX Overhaul 1.0.7 和游戏 2.59.0.78 的原版 bank 做了离线验证：逐字节比对导出 ZIP，除改动字段外全部相同。
- Windows 版由 GitHub Actions 在 Windows 上测试和打包，开发时也在 Wine 11.20 里测过界面和导出。
- 没有系统地在游戏里试听。音量变化需要在游戏里确认。
- 社区乘员语音包的方式只用改名后的样本 bank 验证过。

## 从源码运行

需要 Python 3.10 或更新版本，以及带 Tk 的 Python。Linux 发行版通常要另装 `python3-tk` 或 `tk`。

```sh
python3 app.py
```

命令行：

```sh
python3 bank_volume.py inspect pack.zip --events
python3 bank_volume.py export pack.zip --gain aircraft_engine_own=50 --gain missile=25
python3 bank_volume.py export "/path/to/War Thunder" --gain crew_ground=70
```

未指定的类别保持 100%，类别键见 `inspect` 输出的 `counts`。`--output-root` 指定输出目录。

## 测试和打包

```sh
ruff check .
python3 -m unittest discover -s . -v
./build.sh
```

窗口测试需要显示服务，Linux 上可以用 `xvfb-run -a`。部分测试需要样本包：把 `RCSM_Build_September_7_2026.zip` 和 `OPEX+Overhaul+1.0.7.zip` 放进 `samples/`，没有时这些测试会跳过。样本包是第三方作品，不在仓库里。

`build.sh` 用 PyInstaller 6.22.3 在当前系统打包。`build-windows.sh` 在 Linux 上通过 Wine 打包 Windows 版，会下载并核对 python.org 的 Windows 版 Python 3.13.17。推送 `v*` 标签时，CI 在 Windows 和 Linux 上打包，并发布到 Releases。

## 参考

- [FModBankParser](https://github.com/Masusder/FModBankParser) 是 bank 格式的参考。本工具不依赖它，也不调用 FMOD 或游戏代码。
- [Gaijin 的 FMOD 工程](https://github.com/GaijinEntertainment/fmod_studio_warthunder_for_modders) 是事件和总线结构的公开参考。

## 声明

本项目与 Gaijin Entertainment 无关。War Thunder 是 Gaijin Entertainment 的商标。仓库里不含游戏文件或第三方音效包。修改游戏音效的风险由使用者自负。

## 许可证

[MIT](LICENSE)。Release 里的程序打包了 Python 和 Tcl/Tk，它们的许可证随程序一起发布。
