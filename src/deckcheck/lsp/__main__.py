"""Start the language server (M2 spec §3): below-normal CPU priority, and a watchdog that stops the process with
exit code 75 when its memory passes the budget, so the client pauses deckcheck instead of restarting it."""
import os
import sys
import threading
import time

PAUSE = 75


def lower_priority() -> None:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
        # PROCESS_MODE_BACKGROUND_BEGIN: disk and memory priority lowered too, so a check never slows the editor's
        # own reads (opening a 169 MB include during a Yaris check, M2b harm gate)
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00100000)
    else:
        os.nice(10)


def rss_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(pmc)
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.WorkingSetSize
    if sys.platform.startswith("linux"):
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS


def watch(budget: int, rss=rss_bytes, stop=None, period: float = 0.25, sleep=time.sleep) -> None:
    while True:
        if rss() > budget:
            (stop or (lambda: os._exit(PAUSE)))()
            return
        sleep(period)


def start_watchdog(budget_mb: int) -> None:
    def stop():
        sys.stderr.write(f"deckcheck: memory budget {budget_mb} MB exceeded; pausing\n")
        sys.stderr.flush()
        os._exit(PAUSE)
    threading.Thread(target=watch, args=(budget_mb * 2**20,), kwargs={"stop": stop}, daemon=True,
                     name="deckcheck-memory").start()


def main() -> None:
    lower_priority()
    # The check thread must hand the GIL to the protocol thread promptly (spec §3). Measured on the Yaris, ping
    # during a check: 5 ms and 1 ms intervals give a ~100 ms median, 0.1 ms gives 2 ms. A forced switch only
    # happens while another thread waits, so an idle protocol thread costs the check nothing.
    sys.setswitchinterval(0.0001)
    from deckcheck.lsp.server import server
    server.start_io()


if __name__ == "__main__":
    main()
