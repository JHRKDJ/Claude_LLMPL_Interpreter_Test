"""std.fs: file-system helpers and resource providers (V3 6.14, 7.9).

Providers (usable only as `use` initialisers):
  openRead(path)        yields File   read-only handle
  openWrite(path)       yields File   truncating write
  openAppend(path)      yields File
  openAtomicWrite(path) yields File   writes go to a temp file; normal exit commits
                                      (rename), exception/cancellation/abandonment roll
                                      back (delete temp) — a transaction-like resource
                                      exercising the four exit classes (V3 8.6)
  tempDir()             yields Dir    directory removed on every exit

Recoverable failures are the standard errors FileNotFound / PermissionDenied /
IOFailure (category IO).
"""
from __future__ import annotations

import os
import shutil
import tempfile

from ..core_types import FILE_NOT_FOUND, IO_FAILURE, NONE, PERMISSION_DENIED, make_error, some
from ..signals import Fault, Thrown
from ..values import UNIT, FrozenList, ResourceHandle
from .common import want_str
from .registry import method, module_fn, prop

IO_EFFECT = frozenset({"core.FileNotFound", "core.PermissionDenied", "core.IOFailure"})


def io_error(interp, e: OSError, path: str, span) -> Thrown:
    if isinstance(e, FileNotFoundError):
        err = make_error(FILE_NOT_FOUND, path=path)
    elif isinstance(e, PermissionError):
        err = make_error(PERMISSION_DENIED, path=path)
    else:
        err = make_error(IO_FAILURE, path=path, detail=f"{type(e).__name__}: {e.strerror or e}")
    return Thrown(err, interp.new_provenance(span))


class FileHandle(ResourceHandle):
    lang_kind = "File"
    resource_kind = "File"
    lang_sendable = "reject"
    lang_reject_reason = "resource"

    def __init__(self, path: str, fh, mode: str):
        self.path = path
        self.fh = fh
        self.mode = mode
        self.closed = False

    def lang_display(self) -> str:
        return f"<File {self.path}>"


class DirHandle(ResourceHandle):
    lang_kind = "Dir"
    resource_kind = "Dir"
    lang_sendable = "reject"
    lang_reject_reason = "resource"

    def __init__(self, path: str):
        self.path = path
        self.removed = False


def _check_open(h: FileHandle):
    if h.closed:
        raise Fault("A.RESOURCE.USE_AFTER_RELEASE", f"file {h.path} is closed")


from ..values import TypeValue
from .registry import MODULES
MODULES.setdefault("std.fs", {})["File"] = TypeValue("builtin", "File", (), "File")
MODULES["std.fs"]["Dir"] = TypeValue("builtin", "Dir", (), "Dir")


# ------------------------------------------------------------------ providers
class _FileProvider:
    def __init__(self, path: str, mode: str, atomic: bool = False):
        self.path = path
        self.mode = mode
        self.atomic = atomic
        self.handle = None
        self.tmp = None
        self.name = f"fs.{'openAtomicWrite' if atomic else {'r': 'openRead', 'w': 'openWrite', 'a': 'openAppend'}[mode]}({path})"

    def acquire(self, interp, span):
        try:
            if self.atomic:
                d = os.path.dirname(os.path.abspath(self.path)) or "."
                if not os.path.isdir(d):
                    raise FileNotFoundError(2, "directory does not exist", d)
                fd, self.tmp = tempfile.mkstemp(prefix=".atomic-", dir=d)
                fh = os.fdopen(fd, "w", encoding="utf-8", newline="")
            else:
                fh = open(self.path, self.mode, encoding="utf-8", newline="")
        except OSError as e:
            raise io_error(interp, e, self.path, span)
        self.handle = FileHandle(self.path, fh, self.mode)
        return self.handle

    def release(self, interp, exit_class, span):
        h = self.handle
        if h is None:
            return
        try:
            if not h.closed:
                h.fh.close()
                h.closed = True
            if self.atomic:
                if exit_class == "Normal":
                    os.replace(self.tmp, self.path)
                else:
                    _silent_remove(self.tmp)
        except OSError as e:
            if self.atomic:
                _silent_remove(self.tmp)
            raise io_error(interp, e, self.path, span)

    def abandon_release(self, interp):
        h = self.handle
        if h is not None and not h.closed:
            try:
                h.fh.close()
            finally:
                h.closed = True
        if self.atomic and self.tmp:
            _silent_remove(self.tmp)


def _silent_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


class _TempDirProvider:
    name = "fs.tempDir()"

    def __init__(self):
        self.handle = None

    def acquire(self, interp, span):
        try:
            d = tempfile.mkdtemp(prefix="lang-")
        except OSError as e:
            raise io_error(interp, e, "<tempdir>", span)
        self.handle = DirHandle(d)
        return self.handle

    def release(self, interp, exit_class, span):
        if self.handle is not None and not self.handle.removed:
            self.handle.removed = True
            shutil.rmtree(self.handle.path, ignore_errors=True)

    def abandon_release(self, interp):
        self.release(interp, "Abandoned", None)


@module_fn("std.fs", "openRead", 1, sig="fn(Str) yields File throws FileNotFound | PermissionDenied | IOFailure",
           is_provider=True, effect=IO_EFFECT)
def _open_read(interp, args, span):
    return _FileProvider(want_str(args[0], "path"), "r")


@module_fn("std.fs", "openWrite", 1, sig="fn(Str) yields File throws FileNotFound | PermissionDenied | IOFailure",
           is_provider=True, effect=IO_EFFECT)
def _open_write(interp, args, span):
    return _FileProvider(want_str(args[0], "path"), "w")


@module_fn("std.fs", "openAppend", 1, sig="fn(Str) yields File throws FileNotFound | PermissionDenied | IOFailure",
           is_provider=True, effect=IO_EFFECT)
def _open_append(interp, args, span):
    return _FileProvider(want_str(args[0], "path"), "a")


@module_fn("std.fs", "openAtomicWrite", 1,
           sig="fn(Str) yields File throws FileNotFound | PermissionDenied | IOFailure",
           is_provider=True, effect=IO_EFFECT)
def _open_atomic(interp, args, span):
    return _FileProvider(want_str(args[0], "path"), "w", atomic=True)


@module_fn("std.fs", "tempDir", 0, sig="fn() yields Dir throws IOFailure", is_provider=True,
           effect=frozenset({"core.IOFailure"}))
def _temp_dir(interp, args, span):
    return _TempDirProvider()


# ------------------------------------------------------------------ handle methods
@prop("File", "path", "Str")
def _file_path(interp, recv):
    return recv.path


@method("File", "readAll", 0, sig="fn() -> Str throws IOFailure", effect=frozenset({"core.IOFailure"}))
def _read_all(interp, recv, args, span):
    _check_open(recv)
    try:
        return recv.fh.read()
    except (OSError, ValueError) as e:
        raise io_error(interp, e if isinstance(e, OSError) else OSError(str(e)), recv.path, span)


@method("File", "readLines", 0, sig="fn() -> List[Str] throws IOFailure", effect=frozenset({"core.IOFailure"}))
def _read_lines(interp, recv, args, span):
    _check_open(recv)
    try:
        return FrozenList(tuple(recv.fh.read().splitlines()))
    except (OSError, ValueError) as e:
        raise io_error(interp, e if isinstance(e, OSError) else OSError(str(e)), recv.path, span)


@method("File", "readLine", 0, sig="fn() -> Str? throws IOFailure", effect=frozenset({"core.IOFailure"}))
def _read_line(interp, recv, args, span):
    _check_open(recv)
    try:
        line = recv.fh.readline()
    except (OSError, ValueError) as e:
        raise io_error(interp, e if isinstance(e, OSError) else OSError(str(e)), recv.path, span)
    if line == "":
        return NONE
    return some(line[:-1] if line.endswith("\n") else line)


@method("File", "write", 1, sig="fn(Str) -> Unit throws IOFailure", effect=frozenset({"core.IOFailure"}))
def _write(interp, recv, args, span):
    _check_open(recv)
    try:
        recv.fh.write(want_str(args[0], "text"))
    except (OSError, ValueError) as e:
        raise io_error(interp, e if isinstance(e, OSError) else OSError(str(e)), recv.path, span)
    return UNIT


@method("File", "writeLine", 1, sig="fn(Str) -> Unit throws IOFailure", effect=frozenset({"core.IOFailure"}))
def _write_line(interp, recv, args, span):
    _check_open(recv)
    try:
        recv.fh.write(want_str(args[0], "text") + "\n")
    except (OSError, ValueError) as e:
        raise io_error(interp, e if isinstance(e, OSError) else OSError(str(e)), recv.path, span)
    return UNIT


@method("File", "close", 0, sig="fn() -> Unit", abandon_safe=True)
def _close(interp, recv, args, span):
    if not recv.closed:
        try:
            recv.fh.close()
        finally:
            recv.closed = True
    return UNIT


@prop("Dir", "path", "Str")
def _dir_path(interp, recv):
    return recv.path


# ------------------------------------------------------------------ convenience functions
@module_fn("std.fs", "readText", 1, sig="fn(Str) -> Str throws FileNotFound | PermissionDenied | IOFailure",
           effect=IO_EFFECT)
def _read_text(interp, args, span):
    path = want_str(args[0], "path")
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except OSError as e:
        raise io_error(interp, e, path, span)
    except UnicodeDecodeError as e:
        raise Thrown(make_error(IO_FAILURE, path=path, detail=f"invalid UTF-8: {e}"), interp.new_provenance(span))


@module_fn("std.fs", "writeText", 2, sig="fn(Str, Str) -> Unit throws FileNotFound | PermissionDenied | IOFailure",
           effect=IO_EFFECT)
def _write_text(interp, args, span):
    path = want_str(args[0], "path")
    text = want_str(args[1], "text")
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError as e:
        raise io_error(interp, e, path, span)
    return UNIT


@module_fn("std.fs", "exists", 1, sig="fn(Str) -> Bool")
def _exists(interp, args, span):
    return os.path.exists(want_str(args[0], "path"))


@module_fn("std.fs", "isDir", 1, sig="fn(Str) -> Bool")
def _is_dir(interp, args, span):
    return os.path.isdir(want_str(args[0], "path"))


@module_fn("std.fs", "listDir", 1, sig="fn(Str) -> List[Str] throws FileNotFound | PermissionDenied | IOFailure",
           effect=IO_EFFECT)
def _list_dir(interp, args, span):
    path = want_str(args[0], "path")
    try:
        return FrozenList(tuple(sorted(os.listdir(path))))
    except OSError as e:
        raise io_error(interp, e, path, span)


@module_fn("std.fs", "makeDirs", 1, sig="fn(Str) -> Unit throws PermissionDenied | IOFailure",
           effect=frozenset({"core.PermissionDenied", "core.IOFailure"}))
def _make_dirs(interp, args, span):
    path = want_str(args[0], "path")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        raise io_error(interp, e, path, span)
    return UNIT


@module_fn("std.fs", "remove", 1, sig="fn(Str) -> Unit throws FileNotFound | PermissionDenied | IOFailure",
           effect=IO_EFFECT)
def _remove(interp, args, span):
    path = want_str(args[0], "path")
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as e:
        raise io_error(interp, e, path, span)
    return UNIT


@module_fn("std.fs", "join", 2, sig="fn(Str, Str) -> Str")
def _join(interp, args, span):
    return os.path.join(want_str(args[0]), want_str(args[1]))
