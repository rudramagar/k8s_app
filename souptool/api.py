import struct
from datetime import datetime
from typing import List

def get_list_msg(
        mode,
        msg_type,
        raw_soup_body,
        fn_packing_string,
        unadjusted_packing_string,
        list_header_length):
    # Check whether the message is an API list response.
    if mode == 'a' and msg_type == 5:
        list_header = struct.unpack(unadjusted_packing_string,
                                    raw_soup_body[:list_header_length])
        list_msg_length = list_header[-1]
        list_msg_type = list_header[-2]
        msg_count = list_header[-3]
        packing_string = fn_packing_string(list_msg_type)
        msg = list_header
        current_pointer = list_header_length
        for i in range(0, msg_count):
            msg += struct.unpack(
                packing_string,
                raw_soup_body[current_pointer:current_pointer + list_msg_length]
            )
            current_pointer += list_msg_length
        return msg

def correct_expected_API_calendar_day_type(mode:str,message_type:str,soup,
        expected_message: List[str],holidays: List[str]=[],)->List[str]:
        """
        Update the Day Type field in the expected message provided by checking the date and changing the type of day expected to 3 if the date is a holiday,2 if the date is on a weekend or 0 if not (Test days are currently not covered). 
        
        This is needed because the scenarios files for the Get Calendar Day requests may now relies on dates dynamically generated.  

        Parameters:
        mode (str): The mode provided when starting the tool.
        message_type (str): The type of the message to update. 
        soup (Object): The Soup message handler used for the scenario.
        expected_message (List[str]): The expected message to update.
        holidays (List[str]): The list of JP holidays.

        Returns:
        List[str]: If the expected message is a Get Calendar API reply then this function returns the message with the Day Type field updated to the correct value. If not then the same message is returned.
        """
        
        #Check if the reply is a get Calendar reply.
        if mode == 'a' and message_type == "2" :
            out_format = '%Y%m%d'
            value= soup.resolve_dynamic_date(expected_message[-2],out_format)
            expected_message[-1] = _calculate_calendar_day(value,holidays)
        return expected_message

def _calculate_calendar_day(date:str, holidays:List[str])->str:
    if date in holidays:
         return "3"
    dt = datetime.strptime(date, "%Y%m%d")
    if dt.weekday() >= 5:
        return "2"
    else:
        return "0"
