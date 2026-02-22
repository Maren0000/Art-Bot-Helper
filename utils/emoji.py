def is_emoji(character: str) -> bool:
    if "<:" in character:
        return True

    code_point = ord(character)
    return (
        code_point in range(0x1F600, 0x1F64F)
        or code_point in range(0x1F300, 0x1F5FF)
        or code_point in range(0x1F680, 0x1F6FF)
        or code_point in range(0x1F700, 0x1F77F)
    )
