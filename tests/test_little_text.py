import pytest

from linkedin_bot.publisher.little_text import escape, to_little_text


def test_plain_text_is_unchanged():
    assert to_little_text("Hola, ¿qué tal? Áéíóú ñ.\n\nFin.") == "Hola, ¿qué tal? Áéíóú ñ.\n\nFin."


@pytest.mark.parametrize("char", list("|{}@[]()<>#\\*_~"))
def test_every_reserved_character_is_escaped(char):
    assert escape(char) == "\\" + char


def test_parentheses_and_bullets_are_escaped():
    assert to_little_text("API (oficial)\n* punto") == "API \\(oficial\\)\n\\* punto"


def test_hashtags_become_templates():
    assert to_little_text("Hola #Python y #IA2026") == (
        "Hola {hashtag|\\#|Python} y {hashtag|\\#|IA2026}"
    )


def test_hashtag_with_accents():
    assert to_little_text("#programación") == "{hashtag|\\#|programación}"


def test_hash_inside_word_is_plain_text():
    assert to_little_text("C# y F#") == "C\\# y F\\#"


def test_lone_hash_is_escaped():
    assert to_little_text("# título") == "\\# título"


def test_hashtag_followed_by_reserved_character():
    assert to_little_text("(#python)") == "\\({hashtag|\\#|python}\\)"
