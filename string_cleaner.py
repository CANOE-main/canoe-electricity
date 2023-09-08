"""
This script removes funky characters from strings to prevent database errors
Written by Ian David Elder for the TEMOA Canada / CANOE model
"""

def string_cleaner(string):

    clean_string = ''.join(letter for letter in string if letter in '- ()' or letter.isalnum())

    return clean_string