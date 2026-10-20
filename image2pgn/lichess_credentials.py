"""User-entered Lichess token; optional Windows-user DPAPI storage, never plaintext."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re


def valid_token(token):
    return isinstance(token, str) and 1 <= len(token) <= 4096 and re.fullmatch(r'[A-Za-z0-9_]+', token) is not None


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('암호화 저장은 Windows에서 지원합니다. 저장 없이 연결할 수 있습니다.')
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    output=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    kernel.LocalFree.restype=ctypes.c_void_p
    flags=1  # CRYPTPROTECT_UI_FORBIDDEN; user-bound, not machine-wide.
    if decrypt:
        fn=crypt.CryptUnprotectData
        fn.argtypes=[ctypes.POINTER(Blob),ctypes.POINTER(wintypes.LPWSTR),ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        args=(ctypes.byref(source),None,None,None,None,flags,ctypes.byref(output))
    else:
        fn=crypt.CryptProtectData
        fn.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        args=(ctypes.byref(source),'ChessLens Lichess token',None,None,None,flags,ctypes.byref(output))
    fn.restype=wintypes.BOOL
    if not fn(*args):
        raise ValueError('Windows 계정 암호화를 처리하지 못했습니다.')
    try:
        return ctypes.string_at(output.pbData,output.cbData)
    finally:
        kernel.LocalFree(output.pbData)


class TokenStore:
    def __init__(self,path=None):
        self.path=path or Path(__file__).resolve().parents[1]/'.tmp/lichess-token.dpapi'
        self._token=''
        self.source='none'
        self.storage_error=False
        env=os.environ.get('CHESSLENS_LICHESS_TOKEN','').strip()
        if valid_token(env):
            self._token=env;self.source='environment'
        elif self.path.is_file():
            try:
                if self.path.stat().st_size > 16*1024:raise ValueError()
                value=protect(self.path.read_bytes(),decrypt=True).decode('utf-8')
                if not valid_token(value):raise ValueError()
                self._token=value;self.source='encrypted'
            except (OSError,ValueError,UnicodeError):
                self.storage_error=True

    def token(self):
        return self._token

    def status(self):
        return dict(configured=bool(self._token),source=self.source,persistent_supported=os.name=='nt',storage_error=self.storage_error)

    def set(self,token,remember=False):
        if not valid_token(token):raise ValueError('Lichess 토큰 형식을 확인하세요.')
        if remember:
            encrypted=protect(token.encode('utf-8'))
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.new')
            try:
                temporary.write_bytes(encrypted)
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        self._token=token
        self.source='encrypted' if remember else 'session'
        self.storage_error=False

    def clear(self):
        self.path.unlink(missing_ok=True)
        self._token='';self.source='none';self.storage_error=False
