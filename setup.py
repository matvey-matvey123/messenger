import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

APP_NAME = "Кокаколик"
FOLDER = "Kokacolik"
EXE_NAME = "Kokacolik.exe"
ICON_NAME = "ikon.ico"


def msg(text, flag=0x40):
    ctypes.windll.user32.MessageBoxW(None, text, "Установка " + APP_NAME, flag)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def make_shortcuts(exe, icon, wdir):
    lines = [
        'Set ws = CreateObject("WScript.Shell")',
        'desktop = ws.SpecialFolders("Desktop")',
        'startDir = ws.SpecialFolders("StartMenu") & "\\Programs"',
        'exe = "' + exe.replace("\\", "\\\\") + '"',
        'icon = "' + icon.replace("\\", "\\\\") + '"',
        'wdir = "' + wdir.replace("\\", "\\\\") + '"',
        'Set sc = ws.CreateShortcut(desktop & "\\' + APP_NAME + '.lnk")',
        'sc.TargetPath = exe',
        'sc.WorkingDirectory = wdir',
        'sc.IconLocation = icon',
        'sc.Save',
        'Set sc = ws.CreateShortcut(startDir & "\\' + APP_NAME + '.lnk")',
        'sc.TargetPath = exe',
        'sc.WorkingDirectory = wdir',
        'sc.IconLocation = icon',
        'sc.Save',
    ]
    vbs = "\r\n".join(lines)
    tmp = os.path.join(tempfile.gettempdir(), "kk_shortcuts.vbs")
    with open(tmp, "w", encoding="utf-16") as f:
        f.write(vbs)
    subprocess.call([os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\wscript.exe", tmp], creationflags=0x08000000)
    try:
        os.remove(tmp)
    except OSError:
        pass


def main():
    if not is_admin():
        msg("Запустите установщик от имени администратора.", 0x10)
        return

    bundle = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    src_exe = os.path.join(bundle, EXE_NAME)
    src_icon = os.path.join(bundle, ICON_NAME)
    if not os.path.isfile(src_exe):
        msg("Не найден файл " + EXE_NAME, 0x10)
        return

    target_dir = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), FOLDER)
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copyfile(src_exe, os.path.join(target_dir, EXE_NAME))
        if os.path.isfile(src_icon):
            shutil.copyfile(src_icon, os.path.join(target_dir, ICON_NAME))
    except Exception as e:
        msg("Не удалось установить программу:\n" + str(e), 0x10)
        return

    make_shortcuts(
        os.path.join(target_dir, EXE_NAME),
        os.path.join(target_dir, ICON_NAME),
        target_dir,
    )

    try:
        subprocess.Popen([os.path.join(target_dir, EXE_NAME)])
    except Exception:
        pass

    msg(
        "Программа успешно установлена в:\n"
        + target_dir
        + "\n\nЯрлык создан на рабочем столе и в меню Пуск.\n\nПрограмма запускается автоматически.",
        0x40,
    )


if __name__ == "__main__":
    main()