#!/usr/bin/env python3
"""
Probe the List Reply: login, send List Request, dump the RAW reply bytes
and decode just the list header so we see the ME's actual row length and
row type. No souptool decode - pure bytes. Python 3.6 safe.

Usage: python3 probe_list.py 10.68.72.94 11005 XBAND1 prc123 [ref_type]
  ref_type: 7 = users (default), 2 = entry points
"""
import socket
import struct
import sys


def hexdump(b):
    return " ".join("{:02x}".format(x) for x in b) if b else "(empty)"


def build_login(user, pw, session="", seq="1"):
    body = b"L" + user.encode().ljust(6)[:6] + pw.encode().ljust(10)[:10] \
        + session.encode().rjust(10)[:10] + seq.encode().rjust(20)[:20]
    return struct.pack(">H", 47) + body


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            break
        buf += c
    return buf


def read_soup_packet(s):
    """Read one soup packet: 2-byte length + (length) bytes of body."""
    hdr = recv_exact(s, 2)
    if len(hdr) < 2:
        return None, None
    length = struct.unpack(">H", hdr)[0]
    body = recv_exact(s, length)
    return length, body


def main():
    if len(sys.argv) < 5:
        print("usage: python3 probe_list.py <host> <port> <user> <pw> [ref_type]")
        return 2
    host, port, user, pw = sys.argv[1:5]
    ref_type = int(sys.argv[5]) if len(sys.argv) > 5 else 7

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(6.0)
    s.connect((host, int(port)))

    # Login
    s.sendall(build_login(user, pw))
    ln, body = read_soup_packet(s)
    if not body or chr(body[0]) != "A":
        print("login not accepted:", hexdump(body)); return 1
    print("login accepted. session/seq:", hexdump(body[1:]))

    # Send List Request (14) as unsequenced 'U': [len][U] then api payload
    # api payload little-endian: msg_type(1)=14, corr_id(8)=1001, ref_type(2)
    api = struct.pack("<B", 14) + struct.pack("<Q", 1001) + struct.pack("<H", ref_type)
    soup = struct.pack(">H", 1 + len(api)) + b"U" + api
    print("\nsent List Request ref_type={}: {}".format(ref_type, hexdump(soup)))
    s.sendall(soup)

    # Read reply packets and decode the list header.
    for pkt in range(5):
        ln, body = read_soup_packet(s)
        if body is None:
            print("no more data / closed"); break
        soup_type = chr(body[0])
        print("\n--- reply packet {} (soup_len={}, soup_type={!r}) ---".format(pkt, ln, soup_type))
        print("raw body:", hexdump(body))
        if soup_type not in ("S", "F"):
            print("(not sequenced data)"); continue
        # API payload starts at body[1:]. List Reply (type 5) header, little-endian:
        # msg_type(1) corr_id(8) page(4) next_page(4 signed) msg_count(4)
        # list_msg_type(1) list_msg_length(4)
        p = body[1:]
        if len(p) < 26:
            print("payload too short for list header"); continue
        mt = p[0]
        corr = struct.unpack("<Q", p[1:9])[0]
        page = struct.unpack("<I", p[9:13])[0]
        next_page = struct.unpack("<i", p[13:17])[0]
        count = struct.unpack("<I", p[17:21])[0]
        row_type = p[21]
        row_len = struct.unpack("<I", p[22:26])[0]
        print("  msg_type      :", mt, "(5 = List Reply)")
        print("  correlation_id:", corr)
        print("  page          :", page)
        print("  next_page     :", next_page)
        print("  message_count :", count)
        print("  ROW TYPE      :", row_type)
        print("  ROW LENGTH    :", row_len, "  <-- the ME's actual per-row size")
        header_len = 26
        remaining = len(p) - header_len
        print("  payload after header:", remaining, "bytes =",
              (remaining / row_len if row_len else 0), "rows of", row_len)
        if count and row_len:
            first = p[header_len:header_len + row_len]
            print("  first row raw :", hexdump(first))
        if next_page == -1:
            break
    s.close()


if __name__ == "__main__":
    sys.exit(main())
