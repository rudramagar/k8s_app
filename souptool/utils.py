"""
A collection of common functions that does not belong in any other package.
"""
import json
import string

from .config import PACK_FORMAT, PACK_FORMATS, LENGTH
from .soup_exception import FileReadError

def getv(d, keys):
    """
    Returns values from a nested dictionary.
    ex:
    SOR_MSG_TYPES = {
        'D': 'new',
        'h': 'mkt_state',
        '8': {
            '0': { # ExecTransType
                '0': 'new_ack', # ExecType
                '1': 'fill',
            },
            '1': 'fill',
        }
    }
    getv(SOR_MSG_TYPES, ['D'] returns 'new'
    getv(SOR_MSG_TYPES, ['8', '1'] returns 'fill'
    getv(SOR_MSG_TYPES, ['8', '0', '0'] returns 'new_ack'
    """
    try:
        key = keys.pop(0)
        value = d.get(key)
        if not isinstance(value, dict):
            return value
        return getv(value, keys)
    except Exception: #pylint: disable=broad-except
        return

def load_yaml_config(config_file):
    """
    Reads a yaml file and returns an ordered dictionary.
    """
    with open(config_file) as flh:
        return yaml.safe_load(flh)

def load_json_config(config_file):
    """ Loads json configuration files to a dictionary """
    config = json.load(open(config_file))
    return config

def get_config_type(config_file):
    return config_file.split('.')[-1]

def load_config(config_file, config_type=None):
    try:
        config_type = config_type or get_config_type(config_file)
        if config_type == 'yaml':
            return load_yaml_config(config_file)
        return load_json_config(config_file)
    except json.decoder.JSONDecodeError as err:
        raise FileReadError(f"Error in file {config_file}\n{err}")

def bytes_to_printable(byte_array):
    return ''.join(
        (chr(b) if chr(b) in string.printable else ' ')
        for b in byte_array
    )

def sanitize_message(msg):
    """
    removes b' from byte objects.
    """
    #return tuple([repr(item)[2:-1] if isinstance(item, bytes) else item for item in msg])
    msg = tuple([bytes_to_printable(item) if isinstance(item, bytes) else item for item in msg])
    return msg

def get_packing_char(data_type, length):
    """ Get the charactor needed for packing/unpacking data """
    return PACK_FORMAT[data_type].get(str(length), f"{length}s")

def get_packing_char2(data_type, length):
    """ Get the charactor needed for packing/unpacking data """
    if data_type == 'char' and length == 1:
        return 'c'
    return PACK_FORMATS.get(data_type, f"{length}{PACK_FORMATS.get('default')}")

def get_length(data_type):
    return LENGTH.get(data_type)

def merge_dictionary(d, ref):
    if not ref: return d
    new_d = {}
    begin_dik = {}
    end_dik = d.copy()
    for k, v in d.items():
        begin_dik[k] = v
        del end_dik[k]
        if k in ref:
            del begin_dik[k]
            new_d = {**begin_dik, **ref[k], **end_dik}
            begin_dik = {**begin_dik, **ref[k]}
    return new_d if new_d else d
