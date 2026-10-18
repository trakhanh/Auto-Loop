"""Tạo bản cài đặt KT Loop Station.

    .venv\\Scripts\\python.exe packaging\\build.py            # app + bộ cài
    .venv\\Scripts\\python.exe packaging\\build.py --no-setup # chỉ thư mục app (dist\\KTLoopStation)

Các bước: đóng gói bằng PyInstaller → chép FFmpeg (ffmpeg.exe, ffprobe.exe) vào bin\\ → chuẩn bị bộ mẫu test
(đường dẫn tương đối, thư mục Xuat trống) → Inno Setup tạo dist\\KTLoopStation-Setup-<phiên bản>.exe.
FFmpeg lấy từ biến môi trường FFMPEG_DIR, nếu không có thì tìm trên PATH.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
# đóng gói vào buildpp (không đụng bản đang chạy), xong mới chép sang dist\KTLoopStation nếu không bị khoá
APP_DIR = BUILD / "app" / "KTLoopStation"
DIST_APP = DIST / "KTLoopStation"
STAGE = BUILD / "stage"


if hasattr(sys.stdout, "reconfigure"):  # cửa sổ lệnh tiếng Anh (cp1252) vẫn in được tiếng Việt
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def app_version() -> str:
    text = (ROOT / "loopstation" / "ui" / "theme.py").read_text(encoding="utf-8")
    return re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text).group(1)


def write_version_info(ver: str) -> None:
    nums = [int(x) for x in re.findall(r"\d+", ver)][:4]
    nums += [0] * (4 - len(nums))
    t = tuple(nums)
    (PKG / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('042a04b0', [
      StringStruct('CompanyName', 'Khánh Trà'),
      StringStruct('FileDescription', 'KT Loop Station — ghép và loop video, nhạc'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'KTLoopStation'),
      StringStruct('LegalCopyright', 'By Khánh Trà'),
      StringStruct('OriginalFilename', 'KTLoopStation.exe'),
      StringStruct('ProductName', 'KT Loop Station'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x042a, 1200])])
  ]
)
""", encoding="utf-8")


def pyinstaller() -> None:
    log("Đóng gói bằng PyInstaller…")
    subprocess.run([sys.executable, "-m", "PyInstaller", str(PKG / "KTLoopStation.spec"), "--noconfirm", "--clean",
                    "--distpath", str(APP_DIR.parent), "--workpath", str(BUILD / "pyinstaller")], check=True, cwd=ROOT)


def publish_app_dir() -> None:
    """Chép bản app ra dist/KTLoopStation để chạy thử không cần cài. Đang mở app từ đó thì bỏ qua, không xoá gì.

    Đổi tên cả thư mục trước: Windows không cho đổi tên thư mục có file đang chạy, nên không bao giờ xoá dở
    bản app đang mở."""
    if DIST_APP.exists():
        old = DIST_APP.with_name(DIST_APP.name + "_cu")
        shutil.rmtree(old, ignore_errors=True)
        try:
            os.rename(DIST_APP, old)
        except OSError:
            log(f"Bỏ qua cập nhật {DIST_APP} vì app đang mở từ thư mục đó (bộ cài vẫn là bản mới).")
            return
        shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(APP_DIR, DIST_APP)
    log(f"Bản chạy thử (không cần cài): {DIST_APP}")


def find_ffmpeg_dir() -> Path:
    env = os.environ.get("FFMPEG_DIR")
    if env and (Path(env) / "ffmpeg.exe").is_file():
        return Path(env)
    found = shutil.which("ffmpeg")
    if not found:
        sys.exit("Không tìm thấy ffmpeg.exe — đặt biến FFMPEG_DIR trỏ tới thư mục chứa ffmpeg.exe/ffprobe.exe.")
    return Path(found).resolve().parent


def copy_ffmpeg() -> None:
    src = find_ffmpeg_dir()
    log(f"Chép FFmpeg từ {src}")
    dst = APP_DIR / "bin"
    dst.mkdir(parents=True, exist_ok=True)
    for exe in ("ffmpeg.exe", "ffprobe.exe"):  # ffplay không cần: trình xem đã có sẵn trong app
        shutil.copy2(src / exe, dst / exe)
    for lic in (src.parent / "LICENSE", src.parent / "LICENSE.txt"):
        if lic.is_file():
            shutil.copy2(lic, dst / "FFmpeg-LICENSE.txt")
            break
    (dst / "README.txt").write_text(
        "FFmpeg (https://ffmpeg.org) được dùng để mã hoá video/âm thanh. Bản dựng của gyan.dev, giấy phép GPL v3 —\n"
        "xem FFmpeg-LICENSE.txt. Có thể thay bằng bản FFmpeg khác trong Cài đặt của app.\n", encoding="utf-8")


def stage_samples() -> None:
    log("Chuẩn bị bộ mẫu test…")
    sys.path.insert(0, str(ROOT))
    from loopstation.core.project import Project

    dst = STAGE / "Mau-Test"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(ROOT / "Mau-Test", dst, ignore=shutil.ignore_patterns("*.dang-xuat.*", "__pycache__"))
    out = dst / "Xuat"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for proj in dst.glob("*.lsproj"):
        p = Project.load(str(proj))
        p.export.output_dir = str(out)  # → lưu tương đối "Xuat", đúng trên mọi máy
        p.save(str(proj))


def find_iscc() -> Path | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            c = Path(base) / "Inno Setup 6" / "ISCC.exe"
            if c.is_file():
                return c
    found = shutil.which("ISCC")
    return Path(found) if found else None


def make_setup(ver: str) -> Path:
    iscc = find_iscc()
    if iscc is None:
        sys.exit("Chưa có Inno Setup 6 (ISCC.exe). Cài từ https://jrsoftware.org/isdl.php rồi chạy lại.")
    log("Tạo bộ cài bằng Inno Setup…")
    subprocess.run([str(iscc), f"/DAppVersion={ver}", f"/DAppDir={APP_DIR}", f"/DStageDir={STAGE}",
                    f"/DOutDir={DIST}", str(PKG / "installer.iss")], check=True, cwd=PKG)
    return DIST / f"KTLoopStation-Setup-{ver}.exe"


def main() -> None:
    ver = app_version()
    log(f"KT Loop Station {ver}")
    write_version_info(ver)
    pyinstaller()
    copy_ffmpeg()
    publish_app_dir()
    if "--no-setup" in sys.argv:
        log(f"Xong: {APP_DIR}")
        return
    stage_samples()
    setup = make_setup(ver)
    log(f"Xong: {setup} ({setup.stat().st_size / 1024 ** 2:.0f} MB)")


if __name__ == "__main__":
    main()
