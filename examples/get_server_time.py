import os
import time

from py_clob_client.client import ClobClient


def main():
    time_here = time.time()
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")

    client = ClobClient(host)
    server_time = client.get_server_time()
    print(server_time)
    print(time_here)


main()
