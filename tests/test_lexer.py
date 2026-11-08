"""Tokenizer behaviour."""

from plcagent.st.lexer import StSyntaxError, TokKind, tokenize


def test_keywords_and_idents():
    tokens = tokenize("PROGRAM Main END_PROGRAM")
    kinds = [t.kind for t in tokens]
    assert kinds == [TokKind.KW, TokKind.IDENT, TokKind.KW, TokKind.EOF]


def test_time_literal_takes_priority_over_ident():
    tokens = tokenize("T#2s")
    assert tokens[0].kind is TokKind.TIME_LIT


def test_error_position_is_one_based():
    try:
        tokenize("A := @;")
    except StSyntaxError as exc:
        assert exc.line == 1 and exc.col == 6
    else:
        raise AssertionError("expected StSyntaxError")
