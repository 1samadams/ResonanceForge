"""Tkinter GUI for ResonanceForge.

Features:
- Add files via "Add Files..." / "Add Folder..." buttons
- Drag-and-drop (if `tkinterdnd2` is installed; falls back gracefully)
- Per-file status, progress bar, and live log
- LUFS in/out and true-peak reported on completion
- Configurable target LUFS, TP ceiling, saturation, width
- Runs processing on a background thread so the UI stays responsive
"""
from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, ttk, messagebox

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _HAS_DND = True
except Exception:
    _HAS_DND = False

from .config import PipelineConfig
from .pipeline import Pipeline, ProcessReport


AUDIO_EXTS = {".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg"}


@dataclass
class _Msg:
    kind: str                # "status" | "log" | "done" | "error" | "progress"
    index: int = -1
    text: str = ""
    report: Optional[ProcessReport] = None


class ResonanceForgeGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("ResonanceForge — Mastering Pipeline")
        root.geometry("920x640")
        root.minsize(780, 520)

        self.queue: "queue.Queue[_Msg]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.files: list[Path] = []
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "masters"))

        # tunables
        self.target_lufs = tk.DoubleVar(value=-14.0)
        self.true_peak = tk.DoubleVar(value=-1.0)
        self.width = tk.DoubleVar(value=1.10)
        self.sat_mode = tk.StringVar(value="tube")
        self.sat_drive = tk.DoubleVar(value=6.0)
        self.sat_mix = tk.DoubleVar(value=0.25)

        self._build_ui()
        self._poll_queue()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=24)

        # Top: file list
        top = ttk.Frame(self.root, padding=(10, 10, 10, 5))
        top.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(top)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Files", font=("TkDefaultFont", 11, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="Add Files…", command=self._add_files).pack(side=tk.RIGHT, padx=2)
        ttk.Button(header, text="Add Folder…", command=self._add_folder).pack(side=tk.RIGHT, padx=2)
        ttk.Button(header, text="Clear", command=self._clear).pack(side=tk.RIGHT, padx=2)

        cols = ("file", "status", "lufs_in", "lufs_out", "tp")
        self.tree = ttk.Treeview(top, columns=cols, show="headings", height=10)
        self.tree.heading("file", text="File")
        self.tree.heading("status", text="Status")
        self.tree.heading("lufs_in", text="LUFS in")
        self.tree.heading("lufs_out", text="LUFS out")
        self.tree.heading("tp", text="TP (dB)")
        self.tree.column("file", width=380, anchor=tk.W)
        self.tree.column("status", width=140, anchor=tk.W)
        self.tree.column("lufs_in", width=90, anchor=tk.E)
        self.tree.column("lufs_out", width=90, anchor=tk.E)
        self.tree.column("tp", width=90, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.tree.tag_configure("pending", foreground="#666")
        self.tree.tag_configure("running", foreground="#0a66c2")
        self.tree.tag_configure("done", foreground="#148a3d")
        self.tree.tag_configure("error", foreground="#b00020")

        dnd_hint = "Drag & drop audio files here" if _HAS_DND else "(install `tkinterdnd2` for drag-and-drop)"
        ttk.Label(top, text=dnd_hint, foreground="#888").pack(anchor=tk.W, pady=(4, 0))

        if _HAS_DND:
            self.tree.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.tree.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]

        # Middle: settings
        settings = ttk.LabelFrame(self.root, text="Mastering settings", padding=10)
        settings.pack(fill=tk.X, padx=10, pady=(6, 4))

        r = 0
        ttk.Label(settings, text="Output folder:").grid(row=r, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.output_dir, width=60).grid(row=r, column=1, columnspan=3, sticky=tk.EW, padx=6)
        ttk.Button(settings, text="Browse…", command=self._pick_output).grid(row=r, column=4, sticky=tk.E)
        r += 1
        ttk.Label(settings, text="Target LUFS:").grid(row=r, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(settings, from_=-30.0, to=-6.0, increment=0.5, textvariable=self.target_lufs, width=8).grid(row=r, column=1, sticky=tk.W)
        ttk.Label(settings, text="True Peak (dB):").grid(row=r, column=2, sticky=tk.E)
        ttk.Spinbox(settings, from_=-3.0, to=0.0, increment=0.1, textvariable=self.true_peak, width=8).grid(row=r, column=3, sticky=tk.W)
        ttk.Label(settings, text="Stereo width:").grid(row=r, column=4, sticky=tk.E)
        ttk.Spinbox(settings, from_=0.0, to=2.0, increment=0.05, textvariable=self.width, width=8).grid(row=r, column=5, sticky=tk.W)
        r += 1
        ttk.Label(settings, text="Saturation:").grid(row=r, column=0, sticky=tk.W, pady=4)
        ttk.Combobox(settings, textvariable=self.sat_mode, values=["tube", "tape", "exciter"], width=8, state="readonly").grid(row=r, column=1, sticky=tk.W)
        ttk.Label(settings, text="Drive (dB):").grid(row=r, column=2, sticky=tk.E)
        ttk.Spinbox(settings, from_=0.0, to=24.0, increment=0.5, textvariable=self.sat_drive, width=8).grid(row=r, column=3, sticky=tk.W)
        ttk.Label(settings, text="Mix:").grid(row=r, column=4, sticky=tk.E)
        ttk.Spinbox(settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.sat_mix, width=8).grid(row=r, column=5, sticky=tk.W)
        settings.columnconfigure(1, weight=1)

        # Progress + actions
        actions = ttk.Frame(self.root, padding=(10, 4))
        actions.pack(fill=tk.X)
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.run_btn = ttk.Button(actions, text="Start Processing", command=self._start)
        self.run_btn.pack(side=tk.RIGHT)

        # Log
        logf = ttk.LabelFrame(self.root, text="Log", padding=6)
        logf.pack(fill=tk.BOTH, expand=False, padx=10, pady=(4, 10))
        self.log = tk.Text(logf, height=8, wrap=tk.WORD, state=tk.DISABLED, background="#111", foreground="#ddd", insertbackground="#ddd")
        self.log.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self.root, textvariable=self.status_var, anchor=tk.W, relief=tk.SUNKEN).pack(fill=tk.X, side=tk.BOTTOM)

    # ---------- file management ----------
    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[("Audio", "*.wav *.flac *.aif *.aiff *.mp3 *.ogg"), ("All files", "*.*")],
        )
        for p in paths:
            self._add_one(Path(p))

    def _add_folder(self) -> None:
        d = filedialog.askdirectory(title="Select folder")
        if not d:
            return
        for p in Path(d).rglob("*"):
            if p.suffix.lower() in AUDIO_EXTS:
                self._add_one(p)

    def _pick_output(self) -> None:
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.output_dir.set(d)

    def _add_one(self, path: Path) -> None:
        if not path.exists() or path in self.files:
            return
        if path.suffix.lower() not in AUDIO_EXTS:
            return
        self.files.append(path)
        self.tree.insert("", tk.END, iid=str(len(self.files) - 1),
                         values=(str(path), "Pending", "—", "—", "—"),
                         tags=("pending",))

    def _clear(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.files.clear()
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.progress["value"] = 0
        self.status_var.set("Ready.")

    def _on_drop(self, event) -> None:
        # tkinterdnd2 returns a brace-escaped space-separated list
        raw = event.data
        parts: list[str] = []
        buf = ""
        in_brace = False
        for ch in raw:
            if ch == "{":
                in_brace = True
            elif ch == "}":
                in_brace = False
            elif ch == " " and not in_brace:
                if buf:
                    parts.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            parts.append(buf)
        for p in parts:
            path = Path(p)
            if path.is_dir():
                for q in path.rglob("*"):
                    if q.suffix.lower() in AUDIO_EXTS:
                        self._add_one(q)
            else:
                self._add_one(path)

    # ---------- processing ----------
    def _build_config(self) -> PipelineConfig:
        cfg = PipelineConfig()
        cfg.loudness.target_lufs = float(self.target_lufs.get())
        cfg.loudness.true_peak_db = float(self.true_peak.get())
        cfg.stereo.width = float(self.width.get())
        cfg.saturation.mode = self.sat_mode.get()  # type: ignore[assignment]
        cfg.saturation.drive_db = float(self.sat_drive.get())
        cfg.saturation.mix = float(self.sat_mix.get())
        return cfg

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("No files", "Add at least one audio file first.")
            return
        out_dir = Path(self.output_dir.get())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Output folder", f"Cannot create folder:\n{e}")
            return

        cfg = self._build_config()
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.files)
        self.run_btn.state(["disabled"])
        self._log(f"Starting batch: {len(self.files)} file(s) → {out_dir}")
        self.status_var.set("Processing…")

        self.worker = threading.Thread(
            target=self._run_batch, args=(list(self.files), out_dir, cfg), daemon=True
        )
        self.worker.start()

    def _run_batch(self, files: list[Path], out_dir: Path, cfg: PipelineConfig) -> None:
        pipe = Pipeline(cfg)
        for idx, src in enumerate(files):
            self.queue.put(_Msg("status", index=idx, text="Processing"))
            self.queue.put(_Msg("log", text=f"[{idx + 1}/{len(files)}] {src.name} — reading & mastering"))
            try:
                dest = out_dir / (src.stem + "_mastered.wav")
                report = pipe.process(src, dest)
                self.queue.put(_Msg("done", index=idx, report=report))
                self.queue.put(_Msg("log", text=(
                    f"    done → {dest.name}  "
                    f"LUFS {report.lufs_in:.1f} → {report.lufs_out:.1f}  "
                    f"TP {report.true_peak_out_db:.2f} dB"
                )))
            except Exception as e:
                tb = traceback.format_exc(limit=2)
                self.queue.put(_Msg("error", index=idx, text=str(e)))
                self.queue.put(_Msg("log", text=f"    ERROR: {e}\n{tb}"))
            self.queue.put(_Msg("progress", index=idx + 1))
        self.queue.put(_Msg("log", text="Batch complete."))
        self.queue.put(_Msg("status", index=-1, text="__finished__"))

    # ---------- queue pump ----------
    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _handle(self, msg: _Msg) -> None:
        if msg.kind == "log":
            self._log(msg.text)
        elif msg.kind == "progress":
            self.progress["value"] = msg.index
        elif msg.kind == "status":
            if msg.text == "__finished__":
                self.run_btn.state(["!disabled"])
                self.status_var.set("Done.")
                return
            iid = str(msg.index)
            if self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals[1] = msg.text
                self.tree.item(iid, values=vals, tags=("running",))
        elif msg.kind == "done":
            iid = str(msg.index)
            r = msg.report
            if r and self.tree.exists(iid):
                self.tree.item(iid, values=(
                    r.input_path, "Done",
                    f"{r.lufs_in:.1f}", f"{r.lufs_out:.1f}", f"{r.true_peak_out_db:.2f}",
                ), tags=("done",))
        elif msg.kind == "error":
            iid = str(msg.index)
            if self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals[1] = f"Error: {msg.text[:40]}"
                self.tree.item(iid, values=vals, tags=("error",))

    def _log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)


def main() -> None:
    if _HAS_DND:
        root = TkinterDnD.Tk()  # type: ignore[attr-defined]
    else:
        root = tk.Tk()
    ResonanceForgeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
