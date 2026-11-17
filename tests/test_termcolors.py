# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""What the terminal says its colors are: the answers read, a dark or light background, and when not to ask."""

from morann import termcolors


def answer(code, red, green, blue, end="\x1b\\"):
    return f"\x1b]{code};rgb:{red}/{green}/{blue}{end}"


def test_the_answers_are_read():
    reply = (
        answer("10", "c0c0", "caca", "f5f5")
        + answer("11", "1a1a", "1b1b", "2626", "\a")  # BEL ends an answer too
        + answer("4;1", "f7", "76", "8e")  # two digits a channel
        + answer("4;2", "9e9e", "cece", "6a6a")
        + answer("4;4", "7", "a", "f")  # one digit a channel
        + "\x1b[?62;22c"
    )
    colors = termcolors.parse(reply)
    assert colors == termcolors.TerminalColors(
        foreground="#c0caf5", background="#1a1b26", red="#f7768e", green="#9ece6a", blue="#77aaff"
    )
    assert colors.dark and not termcolors.TerminalColors("#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff").dark
    assert termcolors.parse(answer("11", "00", "00", "00")) is None  # one answer is not enough
    assert termcolors.parse("") is None


def test_a_dark_background_is_guessed_from_colorfgbg():
    assert termcolors.dark_background({}) and termcolors.dark_background({"COLORFGBG": "15;0"})
    assert not termcolors.dark_background({"COLORFGBG": "0;15"}) and not termcolors.dark_background(
        {"COLORFGBG": "0;7"}
    )


def test_it_does_not_ask_when_told_not_to():
    assert termcolors.ask({"NO_COLOR": "1"}) is None and termcolors.ask({"MORANN_ASK_COLORS": "0"}) is None
