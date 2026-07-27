import socket
import time
import struct
import sys

from . import utils
from .soup_exception import SoupConnectionError
from . import api
from typing import List, Any
from datetime import datetime, timedelta, timezone,date
import re

class Soup:
    def __init__(self, cfg, mode, stream):
        self.cfg = cfg
        self.mode = mode
        self.fn_msg_type_pos = self._msg_type_pos(mode, stream)
        self.fn_msg_type = self._msg_type(mode)
        self.fn_out_msg_type = self._out_msg_type(mode)
        self.fn_packing_string = self._packing_string(mode)

    def _msg_type_pos(self, mode, stream):
        """
        Position of the message type will depend on whether the protocol is MDROP or not, and whether the
        stream is 'file' or 'socket'. This function will be evaluated during the initialization.
        """
        if self.cfg.main_config['modes'][mode].get('message_type_position') == 'end':
            return lambda msg_length: msg_length - (1 if stream == 'file' else 2)
        return lambda msg_length: 0

    def _msg_type(self, mode):
        if self.cfg.main_config['modes'][mode].get('message_type_type') == 'uint':
            if self.cfg.main_config['modes'][mode].get('encoding') == 'sbe':
                return lambda msg_length, raw_soup_body: struct.unpack('<HHHH', raw_soup_body[0:8])[1]
            if self.cfg.main_config['modes'][mode].get('message_type_length') == 2:
                return lambda msg_length, raw_soup_body: struct.unpack('>H', raw_soup_body[0:2])[0]
            elif self.cfg.main_config['modes'][mode].get('message_type_length') == 1:
                return lambda msg_length, raw_soup_body: struct.unpack('>B', raw_soup_body[0:1])[0]
        return lambda msg_length, raw_soup_body: chr(raw_soup_body[self.fn_msg_type_pos(msg_length)])

    def _out_msg_type(self, mode):
        if self.cfg.main_config['modes'][mode].get('message_type_type') == 'uint':
            return lambda msg_type: str(int(msg_type))
        return lambda msg_type: msg_type

    def _packing_string(self, mode):
        if self.cfg.main_config['modes'][mode].get('encoding') == 'sbe':
            return lambda msg_type: f"<HHHH{self.cfg.sbe_pack_formats[str(msg_type)][1:]}"
        return lambda msg_type: self.cfg.in_pack_format[f"{self.mode}{msg_type}"]

class SoupBinTCP(Soup):
    """ Use this class to read and write Soup messages.
        Simple usage:

        soup = SoupBinTCP(config_object)
        soup.connect_socket(user)
        soup.write(user, message)
        soup.read(user)

        examples for message:
        OUCH New Order - ['47','U','O','359','JNXTESTTST','B','100','1301','DAY','36690','99999','0','','A','0']
        Soup Logout - ['1', 'O']
        """

    def __init__(self, cfg, mode, stream='socket'):
        """ Initializes the class """
        super().__init__(cfg, mode, stream)
        self.msg = ''
        self._helper(stream)

    def _socket_reader(self, sockfd):
        header =  sockfd.recv(3)
        if len(header) == 0:
            raise SoupConnectionError("Session disconnected")
        return header

    def _helper(self, stream):
        if stream == "file":
            self._raw_header = lambda bstream: bstream.read(2)
            self._get_soup_msg_type = lambda raw_soup_header: 'F'
            self._msg_body = lambda msg_length, bstream: bstream.read(msg_length)
            self._soup_header = lambda raw_soup_msg, msg_type: raw_soup_msg if msg_type != 'F' else raw_soup_msg[0:2]
        elif stream == "bin_file":
            self._raw_header = lambda bstream: bstream.read(3)
            self._get_soup_msg_type = lambda raw_soup_header: chr(raw_soup_header[2])
            self._msg_body = lambda msg_length, bstream: bstream.read(msg_length - 1)
            self._soup_header = lambda raw_soup_msg, msg_type: raw_soup_msg if msg_type != 'S' else raw_soup_msg[0:3]
        else:
            self._raw_header = self._socket_reader
            self._get_soup_msg_type = lambda raw_soup_header: chr(raw_soup_header[2])
            self._msg_body = lambda msg_length, sockfd: sockfd.recv(msg_length - 1)
            self._soup_header = lambda raw_soup_msg, msg_type: raw_soup_msg if msg_type != 'S' else raw_soup_msg[0:3]
        if self.cfg.soup_message_types:
            self.__should_process = self.__message_filter
        else:
            self.__should_process = self.__no_message_filter

    def _convert(self, data_type:str, length:int, value:Any, pad:str='right',packing_string:str='>' )->bytes:
        """Convert a field of the outgoing message's payload to bytes.
        The behavior is mostly dependent on the --validate flag.
        If the flag is at True then the type of each field in the message has to match the type set in the config or an exception will be raised.
        If the flag is at False and there is a type mismatch then the field will be converted to a string(utf-8) by default.
        Args:
            data_type (str): The type of the field as defined in the msg configuration. 
            length (int): The size in bytes that the field should have. 
            value (Any): The value to convert to bytes.
            pad (str): The direction the padding should be added. Do not delete it is used for polymorphism. 
        Returns:
            bytes: The field converted to bytes. 
        """
        endian_char:str = "little" if  packing_string[0]== '<' else "big"
        if data_type == 'alpha':
            return str(value).ljust(length).encode('utf-8')[:length]
        elif data_type == 'uint':
            try:
                # attempt to format it as a proper binary integer
                return int(value).to_bytes(length, byteorder=endian_char)
            except (ValueError, TypeError, OverflowError) as e:
                # with --validate we stop the process and raise an exception.
                if self.cfg.validate:
                    raise ValueError(f"Strict mode error: Failed to pack '{value}' as {length}-byte integer. {e}")
                # without --validate we dump the value as string bytes
                return str(value).ljust(length).encode('utf-8')[:length]        
        elif data_type == 'timestamp_ns':
            try:
                nano_epoch:int = self.convert_timestamp_type(value)
                return nano_epoch.to_bytes(length, byteorder=endian_char)
            # users may still try to write the timestamp like before so we try sending it as an int first then default to string.
            except ValueError as e:
                pass
            try:
                return int(value).to_bytes(length, byteorder=endian_char)    
            except ValueError as e:
                if self.cfg.validate:
                    raise ValueError(f"Failed to process timestamp '{value}': {e}")
                return str(value).ljust(length).encode('utf-8')[:length]
        elif data_type == 'calendar':
            try:
                out_format = '%Y%m%d'
                value = self.resolve_dynamic_date(value, out_format)
                date_int  = int(value)
                return date_int.to_bytes(length, byteorder=endian_char)    
            except ValueError as e:
                pass
            try: 
                return int(value).to_bytes(length, byteorder=endian_char)
            except ValueError as e:
                if self.cfg.validate:
                    raise ValueError(f"Failed to process timestamp '{value}': {e}")
                return str(value).ljust(length).encode('utf-8')[:length]
        return str(value).ljust(length).encode('utf-8')[:length]
            
    def convert_timestamp_type(self,value:str) ->int:
        """
        Convert the timestamp_ns string provided to an actual timestamp in nanosecond since epoch.

        Parameters:
        value (str): The value of a timestamp_ns field.

        Returns:
        int: The value converted to a timestamp in nanoseconds since epoch.
        """
        out_format:str = '%Y-%m-%d %H:%M:%S'
        value = self.resolve_dynamic_date(value, out_format)
        try:
            dt_obj = datetime.strptime(value, out_format)
            JST = timezone(timedelta(hours=9))
            dt_obj = dt_obj.replace(tzinfo=JST)
            return int(dt_obj.timestamp() * 1_000_000_000)
        except ValueError:
            return int(value)

    def read(self, stream):
        """ Read soup message from the socket """
        try:
            raw_soup_header = self._read_raw_header(stream)
            msg = self._read_body(stream, raw_soup_header)
            return msg
        except KeyboardInterrupt:
            print("Keyboard Interrupt received. Exiting")
            sys.exit(0)

    def _read_raw_header(self, stream):
        """ Read soup header """
        raw_soup_header = self._raw_header(stream)
        if raw_soup_header:
            return raw_soup_header
        else:
            sys.exit(0)

    @staticmethod
    def _get_packet_length(raw_soup_header):
        """ Generate the soup packet length """
        packing_string = '>' + utils.get_packing_char('uint', 2)
        packet_length = struct.unpack(packing_string, raw_soup_header[0:2])
        return packet_length[0]

    def __get_payload_message_type(self, soup_msg_type, raw_soup_body, msg_length):
        if soup_msg_type in ('S', 'F'):
            return self.fn_msg_type(msg_length, raw_soup_body)

    def __message_filter(self, raw_soup_header, raw_soup_body, msg_length):
        soup_msg_type = self._get_soup_msg_type(raw_soup_header)
        payload_msg_type = self.__get_payload_message_type(soup_msg_type, raw_soup_body, msg_length)
        if soup_msg_type not in self.cfg.soup_message_types:
            return None, None, False
        if payload_msg_type not in self.cfg.message_types:
            return None, None, False
        return soup_msg_type, payload_msg_type, True

    def __no_message_filter(self, raw_soup_header, raw_soup_body, msg_length):
        soup_msg_type = self._get_soup_msg_type(raw_soup_header)
        payload_msg_type = self.__get_payload_message_type(soup_msg_type, raw_soup_body, msg_length)
        return soup_msg_type, payload_msg_type, True

    def _read_body(self, stream, raw_soup_header):
        """ Read soup body """
        msg_length = SoupBinTCP._get_packet_length(raw_soup_header)
        raw_soup_body = self._msg_body(msg_length, stream)
        if self.cfg.binary:
            return raw_soup_header + raw_soup_body

        soup_msg_type, payload_msg_type, should_process = self.__should_process(raw_soup_header, raw_soup_body, msg_length)
        if not should_process:
            return

        raw_soup_msg = raw_soup_header + raw_soup_body
        packing_string = self.cfg.in_pack_format[f"S{soup_msg_type}"]
        soup_data = struct.unpack(packing_string, self._soup_header(raw_soup_msg, soup_msg_type))
        message = soup_data
        if soup_msg_type in ('S', 'F'):
            sequenced_data = self._read_sequenced_data(stream, raw_soup_body, msg_length, payload_msg_type) # Improve
            message += sequenced_data
        return message

    def _read_sequenced_data(self, stream, raw_soup_body, msg_length, msg_type):
        """
        Read sequenced data i.e. ITCH/OUCH or any other higher layer protocol that runs on top
        of Soup.
        """
        packing_string = self.fn_packing_string(msg_type)
        # Mercury's API protocol has a list request/response type. Response
        # contains a list of same message type. This message needs to be
        # decoded separately, as it does not fall within the current decode
        # logic of the souptool.
        msg_length = self.cfg.in_message_length[f"{self.mode}{msg_type}"]
        unpacked_msg = api.get_list_msg(
            self.mode,
            msg_type,
            raw_soup_body,
            self.fn_packing_string,
            packing_string,
            msg_length)
        # If the message is not a list response do the following.
        if not unpacked_msg:
            # Mercury's drop protocol coupled with the SBE implementation has
            # the data type varStringEncoding, which is essentially a string
            # of unknown length. Below if condition is checking whether the
            # length of the data received is larger than the actual message
            # length provided by the protocol's configuration file and then
            # adjusting the packing string if required.
            if (len(raw_soup_body) > msg_length):
                data_length = len(raw_soup_body) - msg_length
                if packing_string[-1] == 'c':
                    packing_string = packing_string[:-1] + utils.get_packing_char('alpha', data_length + 1)
                else:
                    packing_string = packing_string + utils.get_packing_char('alpha', data_length)
            unpacked_msg = struct.unpack(packing_string, raw_soup_body)
        return unpacked_msg

    def _convert_msg(self, msg, mode, msg_type, packing_string)->List[bytes]:
        """Extract each fields in the message and convert them to bytes.
        Args:
            msg (Any): The message to convert to bytes. 
            mode (Any): The mode set up when starting the tool (m flag). 
            msg_type (Any): The type of the message to convert (one of the protocols/* files). 
        Returns:
            List[bytes]: Each field of the message converted to bytes and stored in a list. 
        """
        msg_converted:List[bytes] = []
        protocol_config = self.cfg.protocol_config[mode].get('Out', self.cfg.protocol_config[mode])
        for index, (_, field_details) in enumerate(protocol_config[msg_type].items()):
            msg_converted.append(self._convert(field_details['type'],
                                        field_details['length'],
                                        msg[index],
                                        field_details.get('pad', ''),packing_string))
        return msg_converted

    def _gen_packed_msg(self, msg, mode, msg_type, packing_string)->bytes:
        """Convert the message's payload to bytes.
        Args:
            msg (Any): The payload to convert to bytes. 
            mode (Any): The mode set up when starting the tool (m flag). 
            msg_type (Any): The type of the message to convert (one of the protocols/* files). 
        Returns:
            bytes: The message converted to bytes. 
        """
        msg_converted:List[bytes] = self._convert_msg(msg, mode, msg_type,packing_string)
        #join the list as a binary object
        return b''.join(msg_converted)

    def write(self, stream, msg):
        """ Write soup messages to socket """
        soup_msg_type = msg[1]
        packing_string = self.cfg.out_pack_format[f"S{soup_msg_type}"]
        msg_packed = self._gen_packed_msg(msg, 'S', soup_msg_type,packing_string)
        stream.send(msg_packed)
        outgoing_msg = struct.unpack(packing_string, msg_packed) # rewrite
        if soup_msg_type == 'U':
            outgoing_msg += self._write_unsequenced_data(stream, msg)
        return outgoing_msg

    def _write_unsequenced_data(self, stream, msg):
        """ Write higher layer protocol's data """
        msg_type = self.fn_out_msg_type(msg[2])
        packing_string = self.cfg.out_pack_format[f"{self.mode}{msg_type}"]
        msg_packed = self._gen_packed_msg(msg[2:], self.mode, msg_type,packing_string)
        stream.send(msg_packed)
        return struct.unpack(packing_string, msg_packed) # rewrite

    def resolve_dynamic_date(self, value: Any, out_format:str) -> Any:
        """Parses a dynamic date/time keyword from a scenario file and resolves it into a string.

        The values returneds is based on Japan Standard Time (JST / UTC+9).
        The logic is split between day-based offsets (TODAY keyword ) and time-based offsets (NOW keyword).

        Args:
            value (Any): The input string to parse. 
            
                Rule 1: {TODAY...} keyword supports day offsets + absolute specific times in HH:MM:SS format.
                    '{TODAY}'            -> Today at the current time
                    '{TODAY+20}'          -> 20 days from now
                    '{TODAY 14:30:00}'      -> Today, at 14:30:00 JST
                    '{TODAY-21 09:00:00}' -> 21 days ago at 09:00:00 JST
                    
                Rule 2: {NOW...} keyword supports relative time offsets formatted as HH:MM:SS.
                    '{NOW}'              -> current time in JST
                    '{NOW+00:00:30}'        -> 30 seconds from now
                    '{NOW-01:00:00}'     -> 1 hour ago
                
                Rule 3: {WEEKEND} keyword returns the date of the next Sunday.
                Rule 4: {HOLIDAY} keyword returns the date of the first national holiday within the 20 days slinding window.If there are no holidays within the 20 days window then the current date is returned (so the related test may fail).

            out_format (str): The format of the datetime returned. 

        Returns:
            Any: A formatted JST datetime string if a valid keyword was provided. 
            If not, the original value is returned as-is.
        """
        if not isinstance(value, str):
            return value
        #The delta is used to set the time in JST
        base_date = datetime.now(timezone(timedelta(hours=9)))
        #section managing the date diff keyword
        if value.startswith('{TODAY'):
            # we check if the value of the field matches the expected template provided in the comment above
            match = re.match(r'^\{TODAY([+-]\d+)?(?:\s+(\d{2}:\d{2}:\d{2}))?\}$', value)
            if not match:
                return value
            day_offset_str = match.group(1)
            absolute_time_str = match.group(2)
            #by default everyting is in UTC so we convert to JST
            if day_offset_str:
                base_date += timedelta(days=int(day_offset_str))
            if absolute_time_str:
                hrs, mins, secs = map(int, absolute_time_str.split(':'))
                base_date = base_date.replace(hour=hrs, minute=mins, second=secs, microsecond=0)
            return base_date.strftime(out_format)
        # branch managing the time delta keyword
        elif value.startswith('{NOW'):
            match = re.match(r'^\{NOW(?:([+-])(\d{2}:\d{2}:\d{2}))?\}$', value)
            if not match:
                return value
            sign_str = match.group(1)
            time_offset_str = match.group(2)
            #we need to check if we are adding or removing time from NOW
            if sign_str and time_offset_str:
                sign = 1 if sign_str == '+' else -1
                hrs, mins, secs = map(int, time_offset_str.split(':'))
                #we apply the timedelat for the JSt timezone 
                base_date += timedelta(hours=hrs * sign, minutes=mins * sign, seconds=secs * sign)
            return base_date.strftime(out_format)
        # If any of the keywrods are in the sentence we return the raw value
        elif value == r'{WEEKEND}':
            days_ahead = 6 - base_date.weekday()
            # If today is Sunday then move to next Sunday by adding 7 days
            # not useful now but worth to keep if we start running the automated tests more frequently
            if days_ahead == 0: 
                days_ahead += 7
            base_date += timedelta(days_ahead)
            return base_date.strftime(out_format)
        elif value == r'{HOLIDAY}':
            sliding_window:int =20
            base_date = base_date.date()
            max_date:date = base_date + timedelta(sliding_window)
            min_date:date = base_date - timedelta(sliding_window)
            jp_holidays:list[str] = self.cfg.main_config['jp_holidays']
            for holiday_date in jp_holidays:
                holiday:date = datetime.strptime(holiday_date, "%Y%m%d").date()
                if holiday >= min_date and holiday<=max_date:
                    return holiday.strftime(out_format)
            print("WARNING:Holiday search failed (range: +/- 20 days), the current date has been used instead. Check the jp_holidays configuration in the souptool.json file.")    
            return base_date.strftime(out_format)
        return value

class SoupLogin(SoupBinTCP):
    """
    The whole purpose of this extra Login class is to avoid doing an extra if for checking the padding of a field.
    Soup Login Request message for some strange reason has two right padded fields. This field needs to be checked
    only during the session login. So it makes sense to have this class to do an extra check just during the login.
    """

    def _convert(self, data_type, length, value,pad='right',packing_string='>')->bytes:
        """ Do conversions for the outgoing messages """
        if data_type == 'alpha':
            if pad == 'left':
                return bytes(str(value.rjust(length)), encoding='utf-8')
            return bytes(str(value.ljust(length)), encoding='utf-8')
        endian_char:str = "little" if  packing_string[0]== '<' else "big"
        return int(value).to_bytes(length, byteorder=endian_char)
