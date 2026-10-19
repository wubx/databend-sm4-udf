"""Shared byte-oriented SM4 contract. gmssl supplies the raw block primitive only."""
import re
from typing import Optional
from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT


def parse_mode(value: str) -> Optional[str]:
    if not value.isascii():
        return None
    name = value.upper().replace('-', '_')
    match = re.fullmatch(r'(?:SM4_(?:128_)?)?(ECB|CBC|CFB|CFB128|OFB)', name, flags=re.ASCII)
    if not match:
        return None
    return 'CFB128' if match[1] == 'CFB' else match[1]


def crypt(data: Optional[bytes], key: Optional[bytes], iv: Optional[bytes],
          mode: Optional[str], decrypt: bool) -> Optional[bytes]:
    if data is None or key is None or iv is None or mode is None:
        return None
    mode = parse_mode(mode)
    if mode is None or len(key) != 16 or (mode != 'ECB' and len(iv) != 16):
        return None
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_DECRYPT if decrypt and mode in ('ECB', 'CBC') else SM4_ENCRYPT)
    # Never call crypt_cbc/crypt_ecb: their automatic unpadding is not this contract.
    def block(b: bytes) -> bytes:
        return bytes(sm4.one_round(sm4.sk, b))
    src = bytes(data)
    feedback = bytes(iv)
    out = bytearray()
    if mode in ('ECB', 'CBC'):
        if decrypt:
            if not src or len(src) % 16:
                return None
        else:
            p = 16 - len(src) % 16
            src += bytes([p]) * p
        for offset in range(0, len(src), 16):
            current = src[offset:offset + 16]
            if mode == 'CBC' and not decrypt:
                current = bytes(a ^ b for a, b in zip(current, feedback))
            result = block(current)
            if mode == 'CBC':
                if decrypt:
                    result = bytes(a ^ b for a, b in zip(result, feedback))
                    feedback = current
                else:
                    feedback = result
            out.extend(result)
        if decrypt:
            p = out[-1]
            if not 1 <= p <= 16 or out[-p:] != bytes([p]) * p:
                return None
            del out[-p:]
    else:
        for offset in range(0, len(src), 16):
            current = src[offset:offset + 16]
            stream = block(feedback)
            result = bytes(a ^ b for a, b in zip(current, stream))
            out.extend(result)
            feedback = stream if mode == 'OFB' else (current if decrypt else result)
    return bytes(out)


def encrypt(data: bytes, key: bytes, iv: bytes, mode: str) -> Optional[bytes]:
    return crypt(data, key, iv, mode, False)


def decrypt(data: bytes, key: bytes, iv: bytes, mode: str) -> Optional[bytes]:
    return crypt(data, key, iv, mode, True)
