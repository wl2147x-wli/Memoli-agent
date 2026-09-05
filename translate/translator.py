"""
Voice service abstract class
"""


class Translator(object):
    # 请使用 https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes 指定语言
    def translate(self, query: str, from_lang: str = "", to_lang: str = "en") -> str:
        """
        Translate text from one language to another
        """
        raise NotImplementedError
