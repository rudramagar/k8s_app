"""
Thin config for the ME session manager.

Provides only the attributes soup.py reads, built directly from the API
spec field layouts instead of souptool's XML loader. We only need a
handful of message types (list request/reply, update user state, entry
point / user replies, accept/reject), so the layouts are defined inline.
"""

# API payloads are little-endian (spec: native x86); soup framing is big-endian.
API_ENDIAN = "<"
SOUP_ENDIAN = ">"

# struct pack char per (type, length). alpha -> "<n>s" fixed-width bytes.
_UINT = {1: "B", 2: "H", 4: "I", 8: "Q"}
_SINT = {1: "b", 2: "h", 4: "i", 8: "q"}


def _packing_char(field_type, length):
    """Return the struct format char(s) for one field."""
    if field_type == "alpha":
        return f"{length}s"
    if field_type == "int":
        return _SINT[length]
    return _UINT[length]


def _build_format(endian, fields):
    """Build a struct format string from a list of (name, length, type)."""
    fmt = endian
    for _name, length, ftype in fields:
        fmt += _packing_char(ftype, length)
    return fmt


def _msg_length(fields):
    return sum(length for _name, length, _type in fields)


# --- SoupBinTCP framing layouts (big-endian) --------------------------------
# Each soup packet: 2-byte big-endian length prefix + 1-byte packet type,
# then the type-specific body. soup.py keys these as "S<type>".
#
# We only need the ones this service sends/receives:
#   L = Login Request, A = Login Accepted, J = Login Rejected,
#   U = Unsequenced Data (our API requests go out as U),
#   S = Sequenced Data (API replies come back as S), H = Heartbeat,
#   O = Logout Request.
SOUP_LAYOUTS = {
    # Login Request: len, 'L', username(6), password(10), session(10), seq(20)
    "SL": [("length", 2, "uint"), ("type", 1, "alpha"),
           ("username", 6, "alpha"), ("password", 10, "alpha"),
           ("session", 10, "alpha"), ("seq", 20, "alpha")],
    # Login Accepted: len, 'A', session(10), seq(20)
    "SA": [("length", 2, "uint"), ("type", 1, "alpha"),
           ("session", 10, "alpha"), ("seq", 20, "alpha")],
    # Login Rejected: len, 'J', reason(1)
    "SJ": [("length", 2, "uint"), ("type", 1, "alpha"),
           ("reason", 1, "alpha")],
    # Unsequenced Data: len, 'U'  (payload follows, decoded separately)
    "SU": [("length", 2, "uint"), ("type", 1, "alpha")],
    # Sequenced Data: len, 'S'  (payload follows, decoded separately)
    "SS": [("length", 2, "uint"), ("type", 1, "alpha")],
    # Heartbeat: len, 'H'
    "SH": [("length", 2, "uint"), ("type", 1, "alpha")],
    # Logout Request: len, 'O'
    "SO": [("length", 2, "uint"), ("type", 1, "alpha")],
}

# SoupBinTCP login: Requested Session and Requested Sequence Number are
# RIGHT-justified numeric fields (space-padded on the left). SoupLogin._convert
# applies rjust when a field's config has pad='left'. Username/password are
# left-justified. This matches souptool's "two right padded fields" note.
RIGHT_JUSTIFIED_LOGIN_FIELDS = {"session", "seq"}


# --- API message layouts (little-endian), mode 'a' --------------------------
# Field 0 is always the 1-byte Message Type. Keyed by message-type number
# as a string, matching soup.py's f"{mode}{msg_type}" convention -> "a14".
#
# Inbound = what we send. Outbound = what we receive.
API_IN = {
    # 14 - List Request
    "14": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint"),
           ("reference_data_type", 2, "uint")],
    # 29 - Update User State Request
    "29": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint"),
           ("user_id", 4, "uint"), ("suspension_status", 1, "alpha")],
}

API_OUT = {
    # 0 - Accept Response
    "0": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint")],
    # 3 - Get Entry Point Reply
    # Spec offsets are inconsistent (name fields have blank offsets); spec
    # states payloads are tightly packed, so fields are laid end-to-end in
    # listed order. Row size is asserted against the List Reply header's
    # message_length at runtime.
    "3": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint"),
          ("host_user_id", 4, "uint"), ("client_user_id", 4, "uint"),
          ("protocol", 2, "uint"),
          ("host_user_name", 32, "alpha"), ("client_user_name", 32, "alpha"),
          ("address", 4, "uint"), ("port", 2, "uint"),
          ("remote_address", 4, "uint"), ("remote_port", 2, "uint"),
          ("logon_count", 2, "uint"), ("logon_status", 2, "uint")],
    # 5 - List Reply (header only; rows decoded via api.get_list_msg)
    "5": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint"),
          ("page", 4, "uint"), ("next_page", 4, "int"),
          ("message_count", 4, "uint"), ("list_msg_type", 1, "uint"),
          ("list_msg_length", 4, "uint")],
    # 8 - Reject Response
    "8": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint"),
          ("reject_reason", 2, "uint")],
    # 13 - Get User Reply
    "13": [("msg_type", 1, "uint"), ("correlation_id", 8, "uint"),
           ("user_id", 4, "uint"), ("user_name", 32, "alpha"),
           ("firm_id", 4, "uint"), ("firm_code", 32, "alpha"),
           ("suspension_status", 1, "alpha"), ("short_sell_adjust", 1, "alpha"),
           ("user_type_name", 32, "alpha")],
}


class MercuryConfig:
    """Minimal cfg object satisfying soup.py's attribute reads."""

    def __init__(self):
        self.mode = "a"

        # soup.py: main_config['modes'][mode].get(...)
        self.main_config = {
            "modes": {
                "a": {
                    "message_type_type": "uint",
                    "message_type_length": 1,
                    "message_type_position": "start",
                    "encoding": "api",
                }
            }
        }

        # SBE not used on the admin connection; empty is fine.
        self.sbe_pack_formats = {}

        # Pack formats keyed as soup.py expects.
        self.in_pack_format = {}
        self.out_pack_format = {}
        self.in_message_length = {}
        # 'a' holds API messages; 'S' holds soup-header layouts. soup.py's
        # _convert_msg reads protocol_config[mode][msg_type] for field defs
        # when packing outgoing messages (mode 'S' for the soup header).
        self.protocol_config = {"a": {"Out": {}}, "S": {}}

        # Soup framing formats (same for in and out).
        for key, fields in SOUP_LAYOUTS.items():
            fmt = _build_format(SOUP_ENDIAN, fields)
            self.in_pack_format[key] = fmt
            self.out_pack_format[key] = fmt
            # key is "S<type>"; strip the leading 'S' for the msg_type.
            soup_type = key[1:]
            self.protocol_config["S"][soup_type] = {
                name: {
                    "type": self._sbe_type(ftype, length),
                    "length": length,
                    "pad": "left" if name in RIGHT_JUSTIFIED_LOGIN_FIELDS else "right",
                }
                for name, length, ftype in fields
            }

        # Outbound API messages (what we SEND). soup.py's _convert_msg reads
        # field defs from protocol_config['a']['Out'], so requests go there.
        for mtype, fields in API_IN.items():
            key = f"a{mtype}"
            self.out_pack_format[key] = _build_format(API_ENDIAN, fields)
            self.in_message_length[key] = _msg_length(fields)
            self.protocol_config["a"]["Out"][mtype] = {
                name: {"type": self._sbe_type(ftype, length), "length": length}
                for name, length, ftype in fields
            }

        # Inbound API messages (what we RECEIVE): decoded via in_pack_format on
        # the read path, which does not use protocol_config. Pack formats only.
        for mtype, fields in API_OUT.items():
            key = f"a{mtype}"
            self.in_pack_format[key] = _build_format(API_ENDIAN, fields)
            self.in_message_length[key] = _msg_length(fields)

        # No message filtering: process everything soup reads.
        self.soup_message_types = []
        self.message_types = []
        self.validate = False
        self.binary = False

    @staticmethod
    def _sbe_type(ftype, length):
        """Map our (type,length) to the type name soup.py's _convert expects."""
        if ftype == "alpha":
            return "alpha"
        return "uint"
