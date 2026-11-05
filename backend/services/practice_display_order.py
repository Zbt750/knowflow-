"""Canonical current paper positions: type group, then original ordinal.

This preserves StudyPage's established ordering; ordinal is NOT a display number.
"""
TYPE_RANK={'single_choice':0,'multiple_choice':0,'fill_blank':1,'calculation':2,'proof':2,'subjective':2,'external_exam':3}
def display_key(question_type,ordinal):return TYPE_RANK.get(question_type,3),ordinal
