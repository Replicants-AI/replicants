"""Windows AppContainer transport for the packaged offline Room reader.

The reader receives three pipe handles, its own profile, read/execute permission
on its dedicated bundle, zero network capabilities, and a one-process memory-
limited job. Failure to establish that boundary fails the Room operation.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from replicants.desktop.room import ReaderProcess, RoomError


class SecurityAttributes(c.Structure):
    _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]


class SecurityCapabilities(c.Structure):
    _fields_ = [('sid', c.c_void_p), ('capabilities', c.c_void_p), ('count', w.DWORD), ('reserved', w.DWORD)]


class StartupInfo(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
               ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
               ('xchars', w.DWORD), ('ychars', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
               ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_data', c.c_void_p),
               ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class StartupInfoEx(c.Structure):
    _fields_ = [('info', StartupInfo), ('attributes', c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class BasicLimits(c.Structure):
    _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong), ('flags', w.DWORD),
               ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('processes', w.DWORD),
               ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IoCounters(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops',
                                                'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(c.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', c.c_size_t),
               ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


def _api():
    kernel = c.WinDLL('kernel32', use_last_error=True)
    user = c.WinDLL('userenv', use_last_error=True)
    security = c.WinDLL('advapi32', use_last_error=True)
    ole = c.WinDLL('ole32', use_last_error=True)
    declarations = [
        (kernel, 'CreatePipe', w.BOOL, [c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), c.POINTER(SecurityAttributes), w.DWORD]),
        (kernel, 'SetHandleInformation', w.BOOL, [w.HANDLE, w.DWORD, w.DWORD]),
        (kernel, 'CloseHandle', w.BOOL, [w.HANDLE]),
        (kernel, 'OpenProcess', w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
        (kernel, 'CreateFileW', w.HANDLE, [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(SecurityAttributes), w.DWORD, w.DWORD, w.HANDLE]),
        (kernel, 'CreateJobObjectW', w.HANDLE, [c.c_void_p, w.LPCWSTR]),
        (kernel, 'SetInformationJobObject', w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]),
        (kernel, 'AssignProcessToJobObject', w.BOOL, [w.HANDLE, w.HANDLE]),
        (kernel, 'TerminateJobObject', w.BOOL, [w.HANDLE, w.UINT]),
        (kernel, 'WaitForSingleObject', w.DWORD, [w.HANDLE, w.DWORD]),
        (kernel, 'ResumeThread', w.DWORD, [w.HANDLE]),
        (kernel, 'InitializeProcThreadAttributeList', w.BOOL, [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)]),
        (kernel, 'UpdateProcThreadAttribute', w.BOOL, [c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p]),
        (kernel, 'DeleteProcThreadAttributeList', None, [c.c_void_p]),
        (kernel, 'CreateProcessW', w.BOOL, [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL,
                                         w.DWORD, c.c_void_p, w.LPCWSTR, c.c_void_p, c.POINTER(ProcessInfo)]),
        (kernel, 'LocalFree', w.HANDLE, [w.HANDLE]),
        (ole, 'CoTaskMemFree', None, [c.c_void_p]),
        (user, 'CreateAppContainerProfile', c.c_long, [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]),
        (user, 'GetAppContainerFolderPath', c.c_long, [w.LPCWSTR, c.POINTER(w.LPWSTR)]),
        (user, 'DeleteAppContainerProfile', c.c_long, [w.LPCWSTR]),
        (security, 'ConvertSidToStringSidW', w.BOOL, [c.c_void_p, c.POINTER(w.LPWSTR)]),
        (security, 'FreeSid', c.c_void_p, [c.c_void_p]),
    ]
    for library, name, result, args in declarations:
        function = getattr(library, name)
        function.restype, function.argtypes = result, args
    return kernel, user, security, ole


class WindowsReader:
    def __init__(self, executable: Path):
        self.executable = executable.resolve()
        if os.name != 'nt' or self.executable.name != 'replicants-room-reader.exe' or self.executable.parent.name != 'reader':
            raise RoomError('room_sandbox_unavailable')
        self.kernel, self.user, self.security, self.ole = _api()
        self.process = self.job = None
        self.input = self.output = None
        self.moniker = self.sid_text = ''

    @staticmethod
    def check(ok):
        if not ok: raise RoomError('room_sandbox_setup_failed')

    def acl(self, remove=False):
        command = ['icacls.exe', str(self.executable.parent)]
        command += ['/remove:g', '*' + self.sid_text] if remove else ['/grant', '*' + self.sid_text + ':(OI)(CI)RX']
        result = subprocess.run(command + ['/T', '/Q'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000, timeout=10)
        if not remove: self.check(result.returncode == 0)

    def start(self):
        import msvcrt
        kernel, user, security = self.kernel, self.user, self.security
        self.moniker = 'Replicants.Room.' + uuid.uuid4().hex
        sid = c.c_void_p()
        profile = w.LPWSTR()
        sid_string = w.LPWSTR()
        handles, attributes, initialized = [], None, False
        process = ProcessInfo()
        try:
            self.check(user.CreateAppContainerProfile(self.moniker, 'Replicants Room', 'Private offline reader', None, 0, c.byref(sid)) >= 0)
            self.check(security.ConvertSidToStringSidW(sid, c.byref(sid_string)))
            self.sid_text = sid_string.value
            self.check(user.GetAppContainerFolderPath(self.sid_text, c.byref(profile)) >= 0)
            folder = Path(profile.value)
            temporary = folder / 'Temp'
            temporary.mkdir(exist_ok=True)
            # Parent-created directories inherit the parent's integrity label.
            # Give only this fresh container SID its intended writable scratch area.
            for arguments in (['/grant', '*' + self.sid_text + ':(OI)(CI)M'],
                              ['/setintegritylevel', '(OI)(CI)L']):
                result = subprocess.run(['icacls.exe', str(temporary), *arguments, '/Q'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=0x08000000, timeout=10)
                self.check(result.returncode == 0)
            self.acl()
            inherit = SecurityAttributes(c.sizeof(SecurityAttributes), None, True)
            child_in, parent_in, parent_out, child_out = (w.HANDLE() for _ in range(4))
            self.check(kernel.CreatePipe(c.byref(child_in), c.byref(parent_in), c.byref(inherit), 0))
            handles.extend([child_in.value, parent_in.value])
            self.check(kernel.CreatePipe(c.byref(parent_out), c.byref(child_out), c.byref(inherit), 0))
            handles.extend([parent_out.value, child_out.value])
            self.check(kernel.SetHandleInformation(parent_in, 1, 0))
            self.check(kernel.SetHandleInformation(parent_out, 1, 0))
            null = kernel.CreateFileW('NUL', 0x40000000, 3, c.byref(inherit), 3, 0x80, None)
            self.check(null and null != c.c_void_p(-1).value)
            handles.append(null)
            size = c.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 3, 0, c.byref(size))
            attributes = c.create_string_buffer(size.value)
            self.check(kernel.InitializeProcThreadAttributeList(attributes, 3, 0, c.byref(size)))
            initialized = True
            capabilities = SecurityCapabilities(sid, None, 0, 0)
            self.check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20009, c.byref(capabilities), c.sizeof(capabilities), None, None))
            inherited = (w.HANDLE * 3)(child_in.value, child_out.value, null)
            self.check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, inherited, c.sizeof(inherited), None, None))
            info = StartupInfoEx()
            info.info.cb, info.info.flags = c.sizeof(info), 0x100
            info.info.stdin, info.info.stdout, info.info.stderr = child_in, child_out, null
            info.attributes = c.cast(attributes, c.c_void_p)
            self.job = kernel.CreateJobObjectW(None, None)
            self.check(self.job)
            limits = ExtendedLimits()
            limits.basic.flags, limits.basic.processes = 0x2000 | 0x100 | 0x8, 1
            limits.process_memory = 256 * 1024 * 1024
            self.check(kernel.SetInformationJobObject(self.job, 9, c.byref(limits), c.sizeof(limits)))
            # Job assignment is atomic with creation. A launcher exit cannot leave
            # a reader alive between CreateProcess and a later assignment call.
            jobs = (w.HANDLE * 1)(self.job)
            self.check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x2000D, jobs, c.sizeof(jobs), None, None))
            system = os.environ.get('SystemRoot', 'C:\\Windows')
            # Windows derives the child's LOCALAPPDATA/TEMP from this base.
            # Passing the already redirected AC directory nests Packages twice.
            self.check(folder.name.casefold() == 'ac' and folder.parent.name.casefold() == self.moniker.casefold()
                       and folder.parent.parent.name.casefold() == 'packages')
            local_base = folder.parent.parent.parent
            environment = {'SystemRoot': system, 'WINDIR': system, 'PATH': str(Path(system) / 'System32'),
                'USERPROFILE': str(folder), 'LOCALAPPDATA': str(local_base), 'APPDATA': str(folder),
                'TEMP': str(temporary), 'TMP': str(temporary)}
            block = c.create_unicode_buffer('\0'.join(k + '=' + v for k, v in sorted(environment.items())) + '\0\0')
            command = c.create_unicode_buffer(subprocess.list2cmdline([str(self.executable)]))
            self.check(kernel.CreateProcessW(str(self.executable), command, None, None, True,
                0x08000000 | 0x00080000 | 0x00000400, block, str(folder), c.byref(info), c.byref(process)))
            self.process = process.process
            self.input = os.fdopen(msvcrt.open_osfhandle(parent_in.value, os.O_BINARY), 'wb', buffering=0)
            handles.remove(parent_in.value)
            self.output = os.fdopen(msvcrt.open_osfhandle(parent_out.value, os.O_BINARY), 'rb', buffering=0)
            handles.remove(parent_out.value)
        except Exception:
            self.stop()
            raise
        finally:
            if process.thread: kernel.CloseHandle(process.thread)
            for handle in handles: kernel.CloseHandle(handle)
            if initialized: kernel.DeleteProcThreadAttributeList(attributes)
            if profile: self.ole.CoTaskMemFree(c.cast(profile, c.c_void_p))
            if sid_string: kernel.LocalFree(c.cast(sid_string, w.HANDLE))
            if sid: security.FreeSid(sid)

    def exchange(self, payload):
        if self.process is None: self.start()
        self.input.write((json.dumps(payload) + '\n').encode())
        line = self.output.readline(2_000_001)
        if not line or len(line) > 2_000_000 or not line.endswith(b'\n'):
            raise RoomError('room_browser_disconnected')
        response = json.loads(line)
        if not isinstance(response, dict) or not response.get('ok'): raise RoomError('room_browser_error')
        return response

    def stop(self):
        if self.job:
            self.kernel.TerminateJobObject(self.job, 1)
            if self.process: self.kernel.WaitForSingleObject(self.process, 3000)
        for stream in (self.input, self.output):
            if stream:
                try: stream.close()
                except OSError: pass
        self.input = self.output = None
        if self.process: self.kernel.CloseHandle(self.process)
        if self.job: self.kernel.CloseHandle(self.job)
        self.process = self.job = None
        if self.sid_text:
            try: self.acl(remove=True)
            except (OSError, subprocess.SubprocessError): pass
            self.sid_text = ''
        if self.moniker:
            self.user.DeleteAppContainerProfile(self.moniker)
            self.moniker = ''

def packaged_reader():
    if os.name != 'nt' or not getattr(sys, 'frozen', False): return None
    path = Path(sys.executable).parent / 'reader' / 'replicants-room-reader.exe'
    return ReaderProcess([sys.executable, 'room-reader'], startup_timeout=20, request_timeout=10) if path.is_file() else None


def run():
    """Trusted launcher; its job handle supervises the sandboxed renderer."""
    path = Path(sys.executable).parent / 'reader' / 'replicants-room-reader.exe'
    reader = WindowsReader(path)
    parent = reader.kernel.OpenProcess(0x00100000, False, os.getppid())
    reader.check(parent)
    def watch_parent():
        reader.kernel.WaitForSingleObject(parent, 0xffffffff)
        # Kernel close-on-exit releases our job handle and kills the renderer,
        # including when an interrupted request cannot return to the input loop.
        os._exit(0)
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        while line := sys.stdin.buffer.readline(262145):
            if len(line) > 262144 or not line.endswith(b'\n'): break
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict): raise ValueError('invalid_reader_message')
                response = reader.exchange(payload)
            except (OSError, ValueError, subprocess.SubprocessError):
                reader.stop()
                response = {'ok': False, 'error': 'room_reader_failed'}
            print(json.dumps(response), flush=True)
    finally:
        reader.stop()
