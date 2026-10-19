"""Local Flight startup smoke test; no Databend instance or external network."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import pyarrow.flight as flight

ROOT=Path(__file__).resolve().parents[1]


class Server(unittest.TestCase):
    def test_loopback_server(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        env={**os.environ,'PYTHONPATH':str(ROOT/'python')}
        process=subprocess.Popen([sys.executable,'-m','sm4_udf.server','--bind',f'127.0.0.1:{port}'],
            env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+15
            while True:
                if process.poll() is not None:self.fail(process.stderr.read().decode())
                with socket.socket() as s:
                    if s.connect_ex(('127.0.0.1',port))==0:break
                if time.monotonic()>deadline:self.fail('Server startup timeout')
                time.sleep(.05)
            with flight.FlightClient(f'grpc://127.0.0.1:{port}') as client:
                for name in ['sm4_encrypt_python','sm4_decrypt_python']:
                    info=client.get_flight_info(flight.FlightDescriptor.for_path(name))
                    self.assertEqual(len(info.schema),5)  # 4 inputs + 1 output
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            process.stderr.close()


if __name__=='__main__':unittest.main()
