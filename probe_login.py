#!/usr/bin/env python3
"""
SoupBinTCP login probe - CORRECTED per souptool soup.json.
Login 'L': Username(6) Password(10) right-padded; RequestedSession(10)
and RequestedSequenceNumber(20) LEFT-padded (rjust). PacketLength=47.
Runs on Python 3.6. Pure stdlib.

Usage: python3 probe_login.py 10.68.72.94 11005 a01 prc123
"""
import socket
import struct
import sys


def hexdump(b):
    return " ".join("{:02x}".format(x) for x in b) if b else "(empty)"


def build_login(user, pw, session="", seq="1"):
    # Per soup.json: username/password rjust->NO, they are pad 'right' = ljust.
    # session/seq are pad 'left' = rjust. PacketLength hardcoded 47.
    body = b"L"
    body += user.encode().ljust(6)[:6]        # pad right = ljust
    body += pw.encode().ljust(10)[:10]        # pad right = ljust
    body += session.encode().rjust(10)[:10]   # pad left = rjust
    body += seq.encode().rjust(20)[:20]       # pad left = rjust
    return struct.pack(">H", 47) + body       # length fixed at 47


def try_login(host, port, frame, label, wait=4.0):
    print("\n=== {} ===".format(label))
    print("send ({} bytes): {}".format(len(frame), hexdump(frame)))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(wait)
    try:
        s.connect((host, int(port)))
    except Exception as e:
        print("connect failed:", e); return
    try:
        s.sendall(frame)
    except Exception as e:
        print("send failed:", e); s.close(); return
    got = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                print("server closed. received:", hexdump(got)); break
            got += chunk
            print("recv:", hexdump(got))
            typ = chr(got[2]) if len(got) >= 3 else "?"
            if typ == "A":
                print("  -> LOGIN ACCEPTED"); break
            if typ == "J":
                r = chr(got[3]) if len(got) >= 4 else "?"
                print("  -> LOGIN REJECTED reason={!r}".format(r)); break
    except socket.timeout:
        print("timeout. received:", hexdump(got))
    finally:
        s.close()


def main():
    if len(sys.argv) < 5:
        print("usage: python3 probe_login.py <host> <port> <user> <password>")
        return 2
    host, port, user, pw = sys.argv[1:5]
    try_login(host, port, build_login(user, pw, "", "1"),
              "CORRECT login (rjust session+seq, len=47), seq='1'")
    try_login(host, port, build_login(user, pw, "", "0"),
              "CORRECT login, seq='0'")
    print("\nDone.")


if __name__ == "__main__":
    sys.exit(main())
