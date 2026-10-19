"""Run with python -m sm4_udf.server; plaintext loopback by default.
The pinned SDK forces a plaintext grpc:// listener. Remote use requires an
independently secured TLS gateway/network; this CLI does not claim native TLS.
"""
import argparse
from databend_udf import UDFServer, udf
from .core import decrypt, encrypt
from .compat import database_crypt


@udf(input_types=['BINARY', 'BINARY', 'BINARY', 'STRING'], result_type='BINARY',
     skip_null=True, io_threads=1)
def sm4_encrypt_python(data: bytes, key: bytes, iv: bytes, mode: str):
    return encrypt(data, key, iv, mode)


@udf(input_types=['BINARY', 'BINARY', 'BINARY', 'STRING'], result_type='BINARY',
     skip_null=True, io_threads=1)
def sm4_decrypt_python(data: bytes, key: bytes, iv: bytes, mode: str):
    return decrypt(data, key, iv, mode)


@udf(input_types=['BINARY', 'STRING', 'STRING', 'STRING'], result_type='BINARY',
     skip_null=True, io_threads=1)
def sm4_encrypt_default_iv_python(data, key, iv, mode):
    return database_crypt(data, key, iv, mode, False, 'default_iv')


@udf(input_types=['BINARY', 'STRING', 'STRING', 'STRING'], result_type='BINARY',
     skip_null=True, io_threads=1)
def sm4_decrypt_default_iv_python(data, key, iv, mode):
    return database_crypt(data, key, iv, mode, True, 'default_iv')


@udf(input_types=['BINARY', 'STRING', 'STRING', 'STRING'], result_type='BINARY',
     skip_null=True, io_threads=1)
def sm4_encrypt_explicit_iv_python(data, key, iv, mode):
    return database_crypt(data, key, iv, mode, False, 'explicit_iv')


@udf(input_types=['BINARY', 'STRING', 'STRING', 'STRING'], result_type='BINARY',
     skip_null=True, io_threads=1)
def sm4_decrypt_explicit_iv_python(data, key, iv, mode):
    return database_crypt(data, key, iv, mode, True, 'explicit_iv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1:8815')
    args = parser.parse_args()
    server = UDFServer(args.bind)
    server.add_function(sm4_encrypt_python)
    server.add_function(sm4_decrypt_python)
    for function in (sm4_encrypt_default_iv_python, sm4_decrypt_default_iv_python,
                     sm4_encrypt_explicit_iv_python, sm4_decrypt_explicit_iv_python):
        server.add_function(function)
    server.serve()


if __name__ == '__main__':
    main()
