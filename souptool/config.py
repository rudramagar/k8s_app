"""
Contains the constants
"""
# Format charactors for struct library
PACK_FORMAT = {
    'uint': {
        '1': 'B',
        '2': 'H',
        '4': 'I',
        '8': 'Q'
    },
    'int': {
        '1': 'b',
        '2': 'h',
        '4': 'i',
        '8': 'q'
    },
    'alpha': {
        '1': 'c'
    },
    'timestamp_ns':{
        '1': 'B',
        '2': 'H',
        '4': 'I',
        '8': 'Q'
    },
    'calendar':{
        '1': 'B',
        '2': 'H',
        '4': 'I',
        '8': 'Q'
    },
    'float':{
       '2':'e',
       '4':'f',
       '8':'d', 
    }
}

PACK_FORMATS = {
    'int8': 'b',
    'int16': 'h',
    'int32': 'i',
    'int64': 'q',
    'uint8': 'B',
    'uint16': 'H',
    'uint32': 'I',
    'uint64': 'Q',
    'float': 'I',
    'default': 's'
}

LENGTH = {
    'int8': 1,
    'int16': 2,
    'int32': 4,
    'int64': 8,
    'uint8': 1,
    'uint16': 2,
    'uint32': 4,
    'uint64': 8,
    'float': 4
}

DEFAULTS = {
    'mode': 'I',
    'board': 'DAY',
    'binary': False,
    'user': 'i01',
    'security_id': '1301',
    'seq_num': '0',
    'scenario_dir': 'scenarios',
    'scenario_file': '',
    'fields': False,
    'verbose': False,
    'quit_on_completion': False,
    'continuous': False,
    'run_qa': False,
    'print_heartbeats': False,
    'heartbeat_interval': 10,
    'soup_session': '',
    'amend': False,
    'file_name': '',
    'file_name_binary': '',
    'securities_file': 'cfg/securities.json',
    'message_types': [],
    'soup_message_types': [],
    'validate': False,
}
