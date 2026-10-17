# Build with: pyinstaller --noconfirm --clean packaging/task-runner.spec
from pathlib import Path
import tomllib

from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# SPECPATH is the directory containing this spec file. Its parent is the
# project root, where pyproject.toml and runtime/ live.
ROOT = Path(SPECPATH).resolve().parent
PROJECT_FILE = ROOT / "pyproject.toml"
if not PROJECT_FILE.is_file():
    raise FileNotFoundError(
        f"Could not find pyproject.toml at {PROJECT_FILE}. "
        "Build from the project's packaging/task-runner.spec file."
    )
PROJECT = tomllib.loads(PROJECT_FILE.read_text(encoding="utf-8"))["project"]
ICON_PATH = ROOT / "assets" / "task-runner.ico"
if not ICON_PATH.is_file():
    raise FileNotFoundError(
        f"App icon is missing at {ICON_PATH}. Run python packaging/prepare_icon.py first."
    )
VERSION_TEXT = PROJECT["version"]
VERSION_TUPLE = tuple(int(part) for part in VERSION_TEXT.split("."))
VERSION_TUPLE = (VERSION_TUPLE + (0, 0, 0, 0))[:4]

# Include product/version metadata in the Windows executable. Read the version
# from pyproject.toml to avoid maintaining a second version number.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=VERSION_TUPLE,
        prodvers=VERSION_TUPLE,
        mask=0x3F,
        flags=0,
        OS=0x40004,
        fileType=0x1,
        subtype=0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "task runner contributors"),
                StringStruct("FileDescription", PROJECT["description"]),
                StringStruct("FileVersion", VERSION_TEXT),
                StringStruct("InternalName", "task runner"),
                StringStruct("OriginalFilename", "task-runner.exe"),
                StringStruct("ProductName", "task runner"),
                StringStruct("ProductVersion", VERSION_TEXT),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

datas = [(str(ICON_PATH), "assets")]
binaries = []
hiddenimports = collect_submodules("runtime") + collect_submodules("mistune.plugins")

# These packages include data or native modules that PyInstaller may not collect
# completely through static import analysis alone.
for package in ("pdfplumber", "docx", "openpyxl", "indra_ocr", "onnxruntime"):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "runtime" / "gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "IPython", "notebook", "jupyter", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="task-runner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=version_info,
    icon=str(ICON_PATH),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="task-runner",
)
