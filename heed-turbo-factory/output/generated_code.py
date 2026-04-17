from typing import Dict, Optional

# 模拟一个DTC代码库，实际应用中可以从数据库或外部文件加载
# 键为DTC代码（字符串），值为DTC代码的详细含义（字符串）
DTC_DATABASE: Dict[str, str] = {
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0171": "System Too Lean (Bank 1)",
    "P0420": "Catalyst System Efficiency Below Threshold (Bank 1)",
    "B1000": "Driver Seat Occupant Classification System Fault",
    "C1001": "Brake Control Module Input Power Circuit Malfunction"
}


def query_dtc_meaning(dtc_code: str) -> Optional[str]:
    """
    REQ-001: DTC代码查询接口
    REQ-002: DTC代码含义显示
    根据输入的DTC代码查询其对应的详细含义。

    Args:
        dtc_code: 用户输入的DTC代码 (e.g., "P0300")。

    Returns:
        如果找到匹配的DTC代码，则返回其详细含义 (str)；
        否则返回 None。
    """
    # REQ-001: 提供一个接口，允许用户输入DTC代码。
    # REQ-002: 查询并显示该DTC代码对应的详细含义。
    return DTC_DATABASE.get(dtc_code)


def display_dtc_info(dtc_code: str) -> str:
    """
    REQ-002: DTC代码含义显示
    REQ-003: 无匹配DTC提示
    处理DTC代码的查询并生成用户可读的输出信息。

    Args:
        dtc_code: 用户输入的DTC代码 (e.g., "P0300")。

    Returns:
        包含DTC代码含义或未找到提示的字符串。
    """
    meaning = query_dtc_meaning(dtc_code)

    if meaning:
        # REQ-002: 显示DTC代码对应的详细含义。
        return f"DTC Code: {dtc_code}\nMeaning: {meaning}"
    else:
        # REQ-003: 如果输入的DTC代码不存在或无效，给出未找到的提示。
        return f"Error: DTC code '{dtc_code}' not found or is invalid. Please check the code and try again."


if __name__ == '__main__':
    # 示例用法：
    print("--- DTC Code Lookup Examples ---")

    # Test Case 1: Valid DTC code
    valid_dtc = "P0300"
    print(display_dtc_info(valid_dtc))
    print("-" * 20)

    # Test Case 2: Another valid DTC code
    another_valid_dtc = "P0420"
    print(display_dtc_info(another_valid_dtc))
    print("-" * 20)

    # Test Case 3: Invalid/Non-existent DTC code
    invalid_dtc = "P9999"
    print(display_dtc_info(invalid_dtc))
    print("-" * 20)

    # Test Case 4: Another invalid DTC code
    another_invalid_dtc = "XYZ123"
    print(display_dtc_info(another_invalid_dtc))
    print("-" * 20)