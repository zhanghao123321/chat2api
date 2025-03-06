def set_value_for_key_dict(data, target_key, new_value):
    if isinstance(data, dict):
        for key, value in data.items():
            if key == target_key:
                data[key] = new_value
            else:
                set_value_for_key_dict(value, target_key, new_value)
    elif isinstance(data, list):
        for item in data:
            set_value_for_key_dict(item, target_key, new_value)


def set_value_for_key_list(data, target_key, new_value):
    if isinstance(data, dict):
        for key, value in data.items():
            if key == target_key:
                data[key] = new_value
            else:
                set_value_for_key_list(value, target_key, new_value)
    elif isinstance(data, list):
        for i in range(len(data) - 1):
            if data[i] == target_key:
                data[i + 1] = new_value
            elif isinstance(data[i], (dict, list)):
                set_value_for_key_list(data[i], target_key, new_value)
        if data and isinstance(data[-1], (dict, list)):
            set_value_for_key_list(data[-1], target_key, new_value)