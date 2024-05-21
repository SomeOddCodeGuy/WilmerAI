import json
import os


def ensure_json_file_exists(filepath, initial_data=None):
    """Ensure that the JSON file exists and return its contents.

    If the file does not exist and initial_data is provided,
    write initial_data to the file and return it. Otherwise,
    return an empty list if the file does not exist.

    Args:
        filepath (str): The path to the JSON file.
        initial_data (list, optional): The initial data to write to the file if it does not exist.

    Returns:
        list: The contents of the JSON file, or the provided initial_data if the file was created.
    """
    if not os.path.exists(filepath):
        if initial_data is not None:
            with open(filepath, 'w') as file:
                json.dump(initial_data, file, indent=4)
        else:
            with open(filepath, 'w') as file:
                file.write("[]")
        return initial_data if initial_data is not None else []

    with open(filepath) as file:
        return json.load(file)


def read_chunks_with_hashes(filepath):
    """Read chunks with hashes from a JSON file.

    Args:
        filepath (str): The path to the JSON file containing chunks with hashes that represent
                        the latest user/assistant pair within the chunk

    Returns:
        list: A list of tuples, where each tuple contains a text block and its corresponding hash.
    """
    data_loaded = ensure_json_file_exists(filepath)
    return [(item['text_block'], item['hash']) for item in data_loaded]


def write_chunks_with_hashes(chunks_with_hashes, filepath, overwrite=False):
    """Write chunks with hashes to a JSON file, optionally overwriting existing content.

    Args:
        chunks_with_hashes (list): A list of tuples, where each tuple contains a text block and a hash that
                                    represents the latest user/assistant pair of the chunk
        filepath (str): The path to the JSON file where chunks with hashes will be written.
        overwrite (bool): If True, overwrite the existing file content; otherwise, append to it.
    """
    existing_data = ensure_json_file_exists(filepath)
    new_data = [{'text_block': text_block, 'hash': hash_code} for text_block, hash_code in chunks_with_hashes]

    if overwrite:
        combined_data = new_data
    else:
        combined_data = existing_data + new_data

    with open(filepath, 'w') as file:
        json.dump(combined_data, file, indent=4)


def update_chunks_with_hashes(chunks_with_hashes, filepath, mode='append'):
    """Update chunks with hashes in a JSON file, appending or overwriting based on mode.

    Args:
        chunks_with_hashes (list): A list of tuples, where each tuple contains a text block and a hash that
                                    represents the latest user/assistant pair of the chunk
        filepath (str): The path to the JSON file where chunks with hashes will be updated.
        mode (str): The mode of operation. Use 'append' to add new chunks to the existing data, or
                    'overwrite' to replace the existing data.
    """
    if mode == 'overwrite':
        write_chunks_with_hashes(chunks_with_hashes, filepath, overwrite=True)
    else:
        write_chunks_with_hashes(chunks_with_hashes, filepath, overwrite=False)


def get_logger_filename():
    """
    Returns:
        str: The path to the logging file for Wilmer
    """
    util_dir = os.path.dirname(os.path.abspath(__file__))
    middleware_dir = os.path.dirname(util_dir)
    project_dir = os.path.dirname(middleware_dir)
    return os.path.join(project_dir, "logs", 'wilmerai.log')
