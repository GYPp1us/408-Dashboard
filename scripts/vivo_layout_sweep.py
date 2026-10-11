"""Capture the public template samples on an authorized physical phone."""
import argparse
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--port", type=int, default=5037)
    parser.add_argument("--group", choices=("cards", "islands", "base"), required=True)
    parser.add_argument("--adb", default=r"D:\Android\Sdk\platform-tools\adb.exe")
    args = parser.parse_args()
    if args.serial.startswith("emulator-"):
        raise SystemExit("Use an OriginOS physical phone")
    adb = [args.adb, "-P", str(args.port), "-s", args.serial]
    root = Path(__file__).resolve().parent.parent
    output = root / ".tmp/atomic-island-lab/device/layouts"
    output.mkdir(parents=True, exist_ok=True)

    def run(*command, binary=False):
        result = subprocess.run(adb + list(command), capture_output=True, check=True,
                                timeout=25)
        return result.stdout if binary else result.stdout.decode("utf-8", "replace")

    if run("shell", "getprop", "ro.product.manufacturer").strip().lower() != "vivo":
        raise SystemExit("Expected vivo/iQOO phone")

    def action(name, key=None):
        command = ["shell", "am", "start", "-n",
                   "com.mutsumi.focus.atomiclab/.AtomicLabActivity", "-f", "0x20000000",
                   "--es", "action", name, "--es", "scene", "FOCUS_TIMER"]
        if key:
            command += ["--es", "layout", key]
        run(*command)

    def screenshot():
        return run("exec-out", "screencap", "-p", binary=True)

    keys = {"cards": [f"c{i}" for i in range(1, 6)],
            "islands": [f"r{i}" for i in range(1, 7)],
            "base": [f"b{i}" for i in range(7)]}[args.group]
    results = []
    lock = output / "active-sweep.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit("A sweep owns this phone. Finish it before starting another group.")
    os.write(lock_fd, str(os.getpid()).encode("ascii"))
    os.close(lock_fd)
    try:
        for key in keys:
            action("layout", key)
            time.sleep(.8)
            action("inspect")
            log = run("exec-out", "run-as", "com.mutsumi.focus.atomiclab", "cat",
                      "files/atomic-lab.log")
            if f"版式 {key}：" not in log:
                raise RuntimeError("The requested layout did not reach the experiment activity")
            case_log = log.rsplit(f"版式 {key}：", 1)[1]
            own = [row for row in case_log.splitlines() if "系统记录 id=9405;" in row]
            status = own[-1] if own else "No own notification record"
            (output / f"{key}.log").write_text("\n".join(log.splitlines()[-10:]), encoding="utf-8")
            focus = next((row for row in run("shell", "dumpsys", "window").splitlines()
                          if "mCurrentFocus=" in row), "")
            if not any(package in focus for package in
                       ("com.mutsumi.focus.atomiclab", "com.android.systemui", "com.bbk.launcher2")):
                raise RuntimeError("Phone left the test UI; no global input sent")
            run("shell", "input", "keyevent", "3")
            time.sleep(1)
            png = screenshot()
            (output / f"{key}.png").write_bytes(png)
            picture = Image.open(io.BytesIO(png)).convert("RGB")
            height = 230 if key.startswith("r") else 900
            picture.crop((0, 0, picture.width, height)).save(output / f"{key}-crop.png")
            animation = None
            if key in ("r1", "r3"):
                frames = [picture.crop((0, 0, picture.width, 230))]
                for _ in range(7):
                    time.sleep(.15)
                    frame = Image.open(io.BytesIO(screenshot())).convert("RGB")
                    frames.append(frame.crop((0, 0, frame.width, 230)))
                animation = f"{key}.gif"
                frames[0].save(output / animation, save_all=True, append_images=frames[1:],
                               duration=250, loop=0)
            results.append({"key": key, "classification": status,
                            "accepted": "SUPERX_VALUE=true" in status,
                            "screenshot": f"{key}-crop.png", "animation": animation})
            print(key, status, flush=True)
    finally:
        try:
            action("end")
            time.sleep(.9)
            action("inspect")
            log = run("exec-out", "run-as", "com.mutsumi.focus.atomiclab", "cat", "files/atomic-lab.log")
            print("Cleanup:", log.splitlines()[-1], flush=True)
            if "本应用没有活动通知" not in log.splitlines()[-1]:
                raise RuntimeError("Experiment notification cleanup did not complete")
        finally:
            (output / f"{args.group}-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            lock.unlink()


if __name__ == "__main__":
    main()
