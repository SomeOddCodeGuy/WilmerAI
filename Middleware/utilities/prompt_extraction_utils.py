import re

template = {"Begin_Sys": "[Beg_Sys]",
            "Begin_User": "[Beg_User]",
            "Begin_Assistant": "[Beg_Assistant]"}

discussionIdentifiers = {"discussion_id_start": "[DiscussionId]",
                         "discussion_id_end": "[/DiscussionId]"}


def extract_last_n_turns(prompt, n):
    """
        Extracts the last 'n' turns from a conversation prompt.

        This function processes a conversation prompt that contains a series of user and assistant turns,
        separated by specific template tags. It extracts the last 'n' turns, which may include consecutive
        turns by the same speaker (user or assistant). This will always return at least 1 user turn,
        so if an assistant went 5 times in a row and it takes 6 to pull back a user turn, then even if
        'n' is 1, it will return 6 pairs.

        Parameters:
        prompt (str): The conversation prompt containing the system, user, and assistant turns.
        n (int): The number of dialogue turns to extract from the end of the conversation.

        Returns:
        str: A string containing the last 'n' turns of the conversation, with the oldest turn at the top
              and the newest turn at the bottom.
    """
    # Remove the initial system prompt if it exists
    if prompt.startswith(template['Begin_Sys']):
        prompt = prompt[prompt.index(template['Begin_Sys']) + len(template['Begin_Sys']):]

    # Initialize parts and set up markers for splits
    parts = []
    current_pos = 0

    # Start with assistant if applicable
    if prompt.startswith(template['Begin_Assistant']):
        assistant_index = prompt.find(template['Begin_User'], current_pos)
        if assistant_index == -1:
            assistant_index = len(prompt)
        parts.append((template['Begin_Assistant'], prompt[current_pos:assistant_index]))
        current_pos = assistant_index

    # Continue parsing the rest of the dialogue
    while current_pos < len(prompt):
        if prompt[current_pos:current_pos + len(template['Begin_User'])] == template['Begin_User']:
            end_index = prompt.find(template['Begin_Assistant'], current_pos + len(template['Begin_User']))
            if end_index == -1:
                end_index = len(prompt)
            parts.append((template['Begin_User'], prompt[current_pos:end_index]))
            current_pos = end_index
        elif prompt[current_pos:current_pos + len(template['Begin_Assistant'])] == template['Begin_Assistant']:
            end_index = prompt.find(template['Begin_User'], current_pos + len(template['Begin_Assistant']))
            if end_index == -1:
                end_index = len(prompt)
            parts.append((template['Begin_Assistant'], prompt[current_pos:end_index]))
            current_pos = end_index
        else:
            current_pos += 1  # Move past any characters that aren't user or assistant tags

    # Extract the desired number of dialogue turns from the end
    extracted_parts = []
    dialogue_count = 0

    i = len(parts) - 1
    while i >= 0 and (dialogue_count < n):
        tag, part = parts[i]
        extracted_parts.append(part)

        if tag == template['Begin_User']:
            dialogue_count += 1

        i -= 1

    # Reverse to maintain original conversation flow and join the parts
    extracted_parts.reverse()
    return ''.join(extracted_parts).strip()


def extract_pairs_and_system_prompt_from_wilmer_templated_string(input_string: str, remove_discussion_id=True) -> tuple:
    """
        Extracts the system prompt and conversation pairs from a Wilmer-templated conversation string.

        This function identifies and separates the system prompt from the conversation pairs, which consist of
        user and assistant turns. It also removes the discussion ID from the system prompt if requested.

        Parameters:
        input_string (str): The conversation string containing the system prompt and conversation pairs.
        remove_discussion_id (bool): Whether to remove the discussion ID from the system prompt. Defaults to True.

        Returns:
        tuple: A tuple containing the system prompt (as a string) and a list of conversation pairs (tuples of user and assistant turns).
    """
    # Extract the system prompt and determine the starting position for pair extraction
    system_prompt, start_position = extract_system_prompt(input_string)

    # Extract conversation pairs starting from the end of the system prompt
    pairs = extract_conversation_pairs(input_string, start_position)

    if remove_discussion_id:
        system_prompt = remove_discussion_id_tag(system_prompt)

    return system_prompt, pairs


def extract_system_prompt(input_string: str) -> tuple:
    """
        Extracts the system prompt from the input string.

        This function searches for the system prompt start tag and extracts the text up to the next user or assistant
        turn start tag.

        Parameters:
        input_string (str): The conversation string containing the system prompt.

        Returns:
        tuple: A tuple containing the extracted system prompt (as a string) and the position in the input string
                 where the conversation pairs begin.
    """
    start_index = input_string.find(template["Begin_Sys"])
    if start_index != -1:
        # If there is a system prompt, find the end of it
        next_start = min([input_string.find(template[key], start_index + len(template["Begin_Sys"])) for key in
                          ("Begin_User", "Begin_Assistant")], default=len(input_string))
        system_prompt = input_string[start_index + len(template["Begin_Sys"]):next_start].strip()
        return system_prompt, next_start
    else:
        # No system prompt found, start from the beginning of the string
        return "", 0


def extract_conversation_pairs(input_string: str, current_position: int) -> list:
    """
        Extracts conversation pairs starting from a given position in the input string.

        This function processes the input string from a specified position to identify and extract pairs of user
        and assistant turns, stopping when no more turns are found.

        Parameters:
        input_string (str): The conversation string containing the conversation pairs.
        current_position (int): The index in the input string where the extraction of conversation pairs should begin.

        Returns:
        list: A list of tuples, each containing a user turn and the subsequent assistant turn.
    """
    pairs = []
    while current_position < len(input_string):
        user_start = input_string.find(template["Begin_User"], current_position)
        assistant_start = input_string.find(template["Begin_Assistant"], current_position)
        next_start = min(user_start if user_start != -1 else len(input_string),
                         assistant_start if assistant_start != -1 else len(input_string))

        if next_start == user_start:
            end_user_turn, user_text = get_end_of_turn(input_string, user_start, template["Begin_User"])
            assistant_text, new_position = handle_assistant_response(input_string, end_user_turn)
            pairs.append((user_text, assistant_text))
            current_position = new_position
        elif next_start == assistant_start:
            end_assistant_turn, assistant_text = get_end_of_turn(input_string, assistant_start,
                                                                 template["Begin_Assistant"])
            pairs.append(("", assistant_text))
            current_position = end_assistant_turn
        else:
            break
    return pairs


def get_end_of_turn(input_string: str, start_index: int, begin_tag: str) -> tuple:
    """
        Determines the end position of a conversation turn and extracts the turn's text.

        This function finds the next occurrence of a conversation turn start tag to determine the end of the current
        turn and extracts the text of the current turn.

        Parameters:
        input_string (str): The conversation string containing the conversation turn.
        start_index (int): The index in the input string where the current turn begins.
        begin_tag (str): The start tag indicating the beginning of a conversation turn.

        Returns:
        tuple: A tuple containing the end index of the current turn and the extracted text of the turn.
    """
    # Searching for the next start tags to determine the end of the current turn
    next_tags = [input_string.find(t, start_index + len(begin_tag)) for t in
                 (template["Begin_User"], template["Begin_Assistant"]) if
                 input_string.find(t, start_index + len(begin_tag)) != -1]

    if next_tags:
        # Find the minimum index of the next start tags, ensuring we're not prematurely cutting off the text
        end_turn = min(next_tags)
    else:
        # If no further tags are found, the end of the turn is the end of the string
        end_turn = len(input_string)

    # Extracting the text from the current start index up to the end index determined
    turn_text = input_string[start_index + len(begin_tag):end_turn].strip()

    return end_turn, turn_text


def handle_assistant_response(input_string: str, end_user_turn: int) -> tuple:
    """
        Handles the extraction of the assistant's response following a user turn.

        This function looks for the assistant's response immediately following a user turn and extracts the assistant's
        text, along with the position where the next turn begins.

        Parameters:
        input_string (str): The conversation string containing the assistant's response.
        end_user_turn (int): The index in the input string where the user turn ends.

        Returns:
        tuple: A tuple containing the assistant's response text and the index where the next turn begins.
    """
    assistant_start = input_string.find(template["Begin_Assistant"], end_user_turn)
    if assistant_start != -1 and assistant_start == end_user_turn:
        end_assistant_turn, assistant_text = get_end_of_turn(input_string, assistant_start, template["Begin_Assistant"])
        return assistant_text, end_assistant_turn
    return "", end_user_turn


def extract_pairs_and_system_prompt_from_string(input_string: str) -> tuple:
    """
        Extracts the system prompt and conversation pairs from an input string.

        This function combines the extraction of the system prompt and conversation pairs into a single operation.

        Parameters:
        input_string (str): The conversation string containing the system prompt and conversation pairs.

        Returns:
        tuple: A tuple containing the system prompt (as a string) and a list of conversation pairs (tuples of user and assistant turns).
    """
    system_prompt, current_position = extract_system_prompt(input_string)
    pairs = extract_conversation_pairs(input_string, current_position)
    return system_prompt, pairs


def extract_discussion_id(text):
    """
        Extracts the discussion ID from the input text.

        This function searches for the discussion ID enclosed within specific start and end tags and returns the numeric ID.

        Parameters:
        text (str): The input text containing the discussion ID.

        Returns:
        str: The extracted numeric discussion ID, or None if not found.
    """
    pattern = f'{re.escape(discussionIdentifiers["discussion_id_start"])}(\\d+){re.escape(discussionIdentifiers["discussion_id_end"])}'
    match = re.search(pattern, text)
    if match:
        return match.group(1)  # This returns the numeric ID as a string
    return None


def remove_discussion_id_tag(text):
    """
        Removes the discussion ID tag from the input text.

        This function identifies and removes the discussion ID and its surrounding tags from the input text.

        Parameters:
        text (str): The input text containing the discussion ID tag.

        Returns:
        str: The input text with the discussion ID tag removed.
    """
    pattern = f'{re.escape(discussionIdentifiers["discussion_id_start"])}\\d+{re.escape(discussionIdentifiers["discussion_id_end"])}'
    return re.sub(pattern, '', text)
