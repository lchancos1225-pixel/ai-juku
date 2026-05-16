GRADE_DISPLAY = {
    7: "中1", 8: "中2", 9: "中3",
    "7": "中1", "8": "中2", "9": "中3",
    "grade7": "中1", "grade8": "中2", "grade9": "中3",
}


def grade_label(grade) -> str:
    return GRADE_DISPLAY.get(grade, str(grade))
