"""String-key adapters with explicit, neutrally named IV policies."""
from typing import Optional
from .core import crypt, parse_mode


def database_crypt(data: Optional[bytes], key: Optional[str], iv: Optional[str],
                   mode: Optional[str], decrypt: bool, profile: str) -> Optional[bytes]:
    if data is None or key is None or iv is None or mode is None:
        return None
    if profile not in ('default_iv', 'explicit_iv'):
        return None
    default_iv = profile == 'default_iv'
    mode = parse_mode('ECB' if default_iv and mode == '' else mode)
    if mode is None or (default_iv and len(data) == 0):
        return None
    folded = bytearray(16)
    for i, b in enumerate(key.encode('utf-8')):
        folded[i % 16] ^= b
    vector = bytearray()
    if mode != 'ECB':
        raw = iv.encode('utf-8')
        if not default_iv and len(raw) < 16:
            return None
        vector = bytearray.fromhex('444f524953444f524953444f5249535f') if default_iv else bytearray(16)
        vector[:min(16, len(raw))] = raw[:16]
    return crypt(data, bytes(folded), bytes(vector), mode, decrypt)
