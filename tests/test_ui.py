import socket
import threading
import time

from lefilter.ui import _bind, _handler


def start(stop_after):
    server = _bind(_handler(None), 0)
    server.stop_after = stop_after
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def open_page(port: int) -> socket.socket:
    """What an editor page's EventSource does: hold /api/alive open."""
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(f"GET /api/alive HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: text/event-stream\r\n\r\n".encode())
    got = b""
    while b"retry:" not in got:   # sent once the server counts the page
        got += s.recv(1024)
    assert got.startswith(b"HTTP/1.0 200") and b"text/event-stream" in got
    return s


def test_server_stops_once_the_editors_last_page_closed():
    server, thread = start(0.3)
    port = server.server_port
    a, b = open_page(port), open_page(port)
    a.close()
    time.sleep(0.6)
    assert thread.is_alive()                 # another page is still open
    b.close()
    time.sleep(0.1)
    c = open_page(port)                      # a reload: back before the server gives up
    time.sleep(0.6)
    assert thread.is_alive()
    c.close()
    thread.join(3)
    assert not thread.is_alive()             # serve_forever returned: the program ends, its console window closes
    server.server_close()


def test_server_keeps_running_when_asked_to():
    server, thread = start(None)             # --no-browser / --keep-running
    open_page(server.server_port).close()
    time.sleep(0.5)
    assert thread.is_alive()
    server.shutdown()
    server.server_close()
