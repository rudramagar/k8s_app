"""
Mercury admin-connection client.

Owns a single SoupBinTCP connection to the matching engine's API port.
The Mercury API uses one-command-per-connection semantics for admin
actions, so this client connects, logs in, does its work, and the caller
decides when to reconnect.

Built incrementally: this step covers connect + soup login only.
"""
import socket
import struct

from config import MercuryConfig
from souptool.soup import SoupBinTCP, SoupLogin
from souptool.soup_exception import SoupConnectionError


# Standard SoupBinTCP login-request field values. Session is left blank
# (server assigns / current), sequence "1" requests replay from the start.
# These are overridable so we don't bake in assumptions we can't verify yet.
DEFAULT_SESSION = ""
DEFAULT_SEQUENCE = "1"


class MercuryClient:
    def __init__(self, host, port, user, password,
                 session=DEFAULT_SESSION, sequence=DEFAULT_SEQUENCE):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.session = session
        self.sequence = sequence

        self.cfg = MercuryConfig()
        # SoupLogin handles the login packet's padded fields; SoupBinTCP
        # handles everything after login (data reads/writes).
        self.login_codec = SoupLogin(self.cfg, "a")
        self.soup = SoupBinTCP(self.cfg, "a")
        self.sock = None

    def connect(self):
        """Open the TCP socket to the ME API port."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        return self.sock

    def login(self):
        """Send Login Request ('L'), read Login Accepted ('A') or Rejected ('J')."""
        # soup.write packs every field in protocol_config['S']['L'] in order,
        # starting with the length field. Body length = type byte + payload:
        # 1 + 6 + 10 + 10 + 20 = 47 (matches the souptool OUCH example style
        # where msg[0] is the packet length).
        body_length = (1 + 6 + 10 + 10 + 20)
        login_msg = [
            str(body_length),  # soup packet length (field 0)
            "L",               # soup packet type: Login Request
            self.user,         # username  (right-padded to field width)
            self.password,     # password  (right-padded)
            self.session,      # requested session (blank = server default)
            self.sequence,     # requested sequence number
        ]
        # SoupLogin.write handles the padded login fields correctly.
        outgoing = self.login_codec.write(self.sock, login_msg)
        print(f"[login] sent: {outgoing}")
        print(f"[login] user={self.user!r} session={self.session!r} "
              f"sequence={self.sequence!r}")

        reply = self.soup.read(self.sock)
        return self._interpret_login(reply)

    def _interpret_login(self, reply):
        """reply is the unpacked soup tuple; index 1 is the packet type char."""
        if not reply:
            raise SoupConnectionError("No login reply received")
        soup_type = reply[1]
        if isinstance(soup_type, bytes):
            soup_type = soup_type.decode()
        if soup_type == "A":
            print(f"[login] accepted: {reply}")
            return True
        if soup_type == "J":
            print(f"[login] rejected: {reply}")
            return False
        print(f"[login] unexpected reply type {soup_type!r}: {reply}")
        return False

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    # --- read path: list sessions -------------------------------------------

    # Reference Data Types (spec, List Request field).
    REF_ENTRY_POINT = 2
    REF_USER = 7

    def _send_list_request(self, reference_data_type, correlation_id=1001):
        """Send a List Request (msg 14) as an unsequenced soup packet."""
        # Unsequenced body = 1 (soup type 'U') + API payload. API payload for
        # msg 14 = msg_type(1) + correlation_id(8) + reference_data_type(2) = 11.
        body_length = 1 + self.cfg.in_message_length["a14"]
        # msg layout for soup.write with 'U': [len, 'U', <api fields...>]
        # _write_unsequenced_data packs msg[2:] against out_pack_format['a14'],
        # so msg[2:] must be exactly (msg_type, correlation_id, ref_data_type).
        msg = [str(body_length), "U", "14", correlation_id, reference_data_type]
        outgoing = self.soup.write(self.sock, msg)
        print(f"[list] request ref_type={reference_data_type} sent: {outgoing}")

    def _read_list_pages(self):
        """Read List Reply (msg 5) pages until next_page == -1. Returns rows."""
        rows = []
        while True:
            reply = self.soup.read(self.sock)
            if not reply:
                print("[list] empty read, stopping")
                break
            # reply tuple = soup header (len, type) + list header + N*row fields.
            # List Reply header (from a5 format): page, next_page, message_count,
            # list_msg_type, list_msg_length follow the soup (len,type) pair.
            # soup header is 2 fields, then a5 header is 7 fields:
            # msg_type, correlation_id, page, next_page, message_count,
            # list_msg_type, list_msg_length.
            header = reply[2:9]
            _mt, _corr, page, next_page, msg_count, list_msg_type, list_msg_len = header
            print(f"[list] page={page} next_page={next_page} count={msg_count} "
                  f"row_type={list_msg_type} row_len={list_msg_len}")

            # Runtime assertion: our computed row size must match the ME's.
            expected = self.cfg.in_message_length.get(f"a{list_msg_type}")
            if expected is not None and expected != list_msg_len:
                print(f"[list] WARNING row size mismatch for type {list_msg_type}: "
                      f"config={expected} ME={list_msg_len} "
                      f"(delta {list_msg_len - expected})")

            # Row fields are everything after the 9-field header prefix.
            row_fields = reply[9:]
            rows.extend(self._split_rows(row_fields, list_msg_type, msg_count))

            if next_page == -1:
                break
        return rows

    def _split_rows(self, row_fields, list_msg_type, msg_count):
        """Split the flat decoded row tuple into per-row dicts."""
        if msg_count == 0:
            return []
        field_names = list(self.cfg.protocol_config["a"]["Out"][str(list_msg_type)].keys())
        n = len(field_names)
        rows = []
        for i in range(msg_count):
            chunk = row_fields[i * n:(i + 1) * n]
            row = dict(zip(field_names, chunk))
            rows.append(self._clean_row(row))
        return rows

    @staticmethod
    def _clean_row(row):
        """Decode/strip byte fields (null-padded alpha strings)."""
        cleaned = {}
        for k, v in row.items():
            if isinstance(v, bytes):
                v = v.decode("utf-8", "replace").strip("\x00").strip()
            cleaned[k] = v
        return cleaned

    def list_users(self, correlation_id=1001):
        """List users (msg 14, ref-type 7). Rows carry suspension status A/S."""
        self._send_list_request(self.REF_USER, correlation_id)
        return self._read_list_pages()

    def list_entry_points(self, correlation_id=1001):
        """List entry points (msg 14, ref-type 2). Rows carry logon status."""
        self._send_list_request(self.REF_ENTRY_POINT, correlation_id)
        return self._read_list_pages()
