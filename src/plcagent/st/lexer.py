"""ST subset tokenizer. Positions are 1-based (line, col) for S01 reporting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokKind(Enum):
    IDENT = auto()
    KW = auto()
    NUM = auto()
    TIME_LIT = auto()
    STRING_LIT = auto()
    OP = auto()
    NEWLINE = auto()
    EOF = auto()


KEYWORDS = frozenset({
    "PROGRAM", "END_PROGRAM", "FUNCTION_BLOCK", "END_FUNCTION_BLOCK",
    "VAR_INPUT", "VAR_OUTPUT", "VAR", "END_VAR",
    "IF", "THEN", "ELSIF", "ELSE", "END_IF",
    "CASE", "OF", "END_CASE",
    "FOR", "TO", "BY", "DO", "END_FOR",
    "WHILE", "END_WHILE", "RETURN",
    "AND", "OR", "NOT", "XOR", "MOD",
    "TRUE", "FALSE",
    "BOOL", "BYTE", "INT", "DINT", "UINT", "UDINT", "REAL", "TIME", "STRING",
})


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokKind
    text: str
    line: int
    col: int


class StSyntaxError(SyntaxError):
    """Syntax error with 1-based source position."""

    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(f"{line}:{col}: {message}")
        self.line = line
        self.col = col


_TWO_CHAR_OPS = frozenset({":=", "<>", "<=", ">="})
_ONE_CHAR_OPS = frozenset("()[];:,=<>+-*/&")


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    line, col = 1, 1
    pos, n = 0, len(source)

    def emit(kind: TokKind, text: str, tok_line: int, tok_col: int) -> None:
        tokens.append(Token(kind, text, tok_line, tok_col))

    while pos < n:
        ch = source[pos]

        if ch == "\n":
            emit(TokKind.NEWLINE, "\n", line, col)
            pos += 1
            line += 1
            col = 1
            continue
        if ch in " \t\r":
            pos += 1
            col += 1
            continue
        if source.startswith("//", pos):
            end = source.find("\n", pos)
            pos = n if end < 0 else end
            continue
        if source.startswith("(*", pos):
            end = source.find("*)", pos + 2)
            if end < 0:
                raise StSyntaxError("unterminated block comment", line, col)
            consumed = source[pos:end + 2]
            newlines = consumed.count("\n")
            if newlines:
                line += newlines
                col = len(consumed) - consumed.rfind("\n")
            else:
                col += len(consumed)
            pos = end + 2
            continue

        start_line, start_col = line, col

        if ch.isdigit():
            j = pos
            while j < n and (source[j].isalnum() or source[j] in "._"):
                j += 1
            emit(TokKind.NUM, source[pos:j], start_line, start_col)
            col += j - pos
            pos = j
            continue

        if ch.isalpha() or ch == "_":
            j = pos
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[pos:j]
            if j < n and source[j] == "#" and word.upper() in ("T", "TIME"):
                j += 1
                while j < n and (source[j].isalnum() or source[j] in "._"):
                    j += 1
                emit(TokKind.TIME_LIT, source[pos:j], start_line, start_col)
            else:
                kind = TokKind.KW if word.upper() in KEYWORDS else TokKind.IDENT
                emit(kind, word, start_line, start_col)
            col += j - pos
            pos = j
            continue

        if ch == "'":
            j = pos + 1
            while j < n and source[j] != "'":
                j += 1
            if j >= n:
                raise StSyntaxError("unterminated string literal", line, col)
            emit(TokKind.STRING_LIT, source[pos + 1:j], start_line, start_col)
            col += j + 1 - pos
            pos = j + 1
            continue

        two = source[pos:pos + 2]
        if two in _TWO_CHAR_OPS:
            emit(TokKind.OP, two, start_line, start_col)
            pos += 2
            col += 2
            continue
        if ch in _ONE_CHAR_OPS:
            emit(TokKind.OP, ch, start_line, start_col)
            pos += 1
            col += 1
            continue

        raise StSyntaxError(f"unexpected character {ch!r}", line, col)

    emit(TokKind.EOF, "", line, col)
    return tokens
