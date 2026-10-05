"""Блокировка программ (закрытие процессов) и сайтов (файл hosts)."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("parentssee")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
MAX_PATH = 260
NO_WINDOW = 0x08000000

HOSTS_PATH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
MARK_BEGIN = "# ParentsSee BEGIN — не редактировать вручную"
MARK_END = "# ParentsSee END"


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


# ---------- нормализация ----------

def normalize_exe(name: str) -> str:
    """'Chrome', 'chrome.exe', ' CHROME.EXE ' -> 'chrome.exe'."""
    name = name.strip().lower()
    if not name:
        return ""
    if not name.endswith(".exe"):
        name += ".exe"
    return name


def normalize_domain(value: str) -> str:
    """'https://YouTube.com/watch' -> 'youtube.com'."""
    value = value.strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = value.split("/")[0].split("?")[0]
    if value.startswith("www."):
        value = value[4:]
    return value.strip()


# ---------- блокировка программ ----------

def _iter_processes():
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value or not snapshot:
        return
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return
        while True:
            name = entry.szExeFile.decode("mbcs", errors="replace").lower()
            yield entry.th32ProcessID, name
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)


def _terminate(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


# Никогда не трогаем системные и свои процессы.
_NEVER_KILL = {
    "system", "system idle process", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "smss.exe", "explorer.exe", "dwm.exe",
    "svchost.exe", "pythonw.exe", "python.exe", "taskmgr.exe",
}


def enforce_programs(blocked: list[str]) -> list[str]:
    """Закрывает запущенные программы из списка. Возвращает имена закрытых."""
    targets = {normalize_exe(name) for name in blocked if name.strip()}
    targets -= _NEVER_KILL
    if not targets:
        return []
    killed: list[str] = []
    for pid, name in _iter_processes():
        if name in targets and pid > 4:
            if _terminate(pid):
                killed.append(name)
    if killed:
        log.info("Закрыты программы: %s", ", ".join(sorted(set(killed))))
    return killed


# ---------- блокировка сайтов ----------

def _read_hosts() -> str:
    try:
        return HOSTS_PATH.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _strip_block(text: str) -> str:
    """Убирает прежний блок ParentsSee, оставляя остальной hosts как есть."""
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if line.strip() == MARK_BEGIN:
            inside = True
            continue
        if line.strip() == MARK_END:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "\n".join(out).rstrip("\n")


def sites_currently_blocked() -> list[str]:
    """Домены, которые сейчас перечислены в блоке hosts."""
    text = _read_hosts()
    domains: list[str] = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == MARK_BEGIN:
            inside = True
            continue
        if stripped == MARK_END:
            break
        if inside and stripped and not stripped.startswith("#"):
            parts = stripped.split()
            if len(parts) >= 2:
                domains.append(parts[1])
    return domains


def apply_sites(blocked: list[str]) -> tuple[bool, str]:
    """Переписывает блок ParentsSee в hosts. Требует прав администратора."""
    domains: list[str] = []
    for raw in blocked:
        domain = normalize_domain(raw)
        if domain and domain not in domains:
            domains.append(domain)

    base = _strip_block(_read_hosts())
    if domains:
        block_lines = [MARK_BEGIN]
        for domain in domains:
            block_lines.append(f"127.0.0.1 {domain}")
            block_lines.append(f"127.0.0.1 www.{domain}")
        block_lines.append(MARK_END)
        new_text = base.rstrip("\n") + "\n\n" + "\n".join(block_lines) + "\n"
    else:
        new_text = base.rstrip("\n") + "\n"

    try:
        HOSTS_PATH.write_text(new_text, encoding="utf-8")
    except PermissionError:
        return False, "Нужны права администратора (файл hosts защищён)."
    except OSError as exc:
        return False, f"Не удалось изменить hosts: {exc}"

    _flush_dns()
    log.info("Список сайтов в hosts обновлён: %d шт.", len(domains))
    return True, f"Заблокировано сайтов: {len(domains)}"


def clear_sites() -> tuple[bool, str]:
    return apply_sites([])


def _flush_dns() -> None:
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"], capture_output=True, creationflags=NO_WINDOW
        )
    except OSError:
        pass


def can_edit_hosts() -> bool:
    """Быстрая проверка: можем ли писать в hosts (т.е. есть ли права)."""
    try:
        with open(HOSTS_PATH, "a", encoding="utf-8"):
            return True
    except OSError:
        return False
