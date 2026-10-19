"""Portable byte-oriented SM4 UDF reference implementation."""
from .core import decrypt, encrypt

__all__ = ['encrypt', 'decrypt']
