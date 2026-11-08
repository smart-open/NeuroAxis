"""Spec expression parsing (3.3): turn `when` strings into IrExpr trees.

Uses the ST lexer for tokens so operator semantics stay in one place, but has
its own small parser: spec expressions also allow `a.b` sequence references and
`mode=Manual` equality.
"""

from __future__ import annotations

import re

from plcagent.spec.ir_model import IrExpr
from plcagent.st.lexer import TokKind, tokenize


class SpecExprError(ValueError):
    """Invalid spec expression; message includes position."""


class _ExprParser:
    def __init__(self, source: str) -> None:
        # The ST lexer has no '.' operator; encode member access as Seq#member
        # and decode after tokenizing.
        normalized = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)",
                            r"\1__DOT__\2", source)
        try:
            self._tokens = tokenize(normalized)
        except Exception as exc:
            raise SpecExprError(f"lex error in {source!r}: {exc}") from exc
        self._pos = 0
        self._source = source

    def _peek(self, offset: int = 0):
        index = self._pos + offset
        return self._tokens[index] if index < len(self._tokens) else self._tokens[-1]

    def _advance(self):
        token = self._peek()
        if token.kind is not TokKind.EOF:
            self._pos += 1
        return token

    def _expect_op(self, text: str):
        token = self._advance()
        if token.kind is not TokKind.OP or token.text != text:
            raise SpecExprError(f"expected {text!r} at position {token.col} in {self._source!r}")
        return token

    # precedence: OR < XOR < AND < comparison < NOT < primary
    def parse(self) -> IrExpr:
        if self._peek().kind is TokKind.EOF:
            raise SpecExprError("empty expression")
        expr = self._parse_or()
        if self._peek().kind is not TokKind.EOF:
            token = self._peek()
            raise SpecExprError(
                f"unexpected token {token.text!r} at position {token.col} in {self._source!r}")
        return expr

    def _parse_or(self) -> IrExpr:
        left = self._parse_xor()
        while self._peek().kind is TokKind.KW and self._peek().text == "OR":
            self._advance()
            left = IrExpr(kind="BIN", op="OR", left=left, right=self._parse_xor())
        return left

    def _parse_xor(self) -> IrExpr:
        left = self._parse_and()
        while self._peek().kind is TokKind.KW and self._peek().text == "XOR":
            self._advance()
            left = IrExpr(kind="BIN", op="XOR", left=left, right=self._parse_and())
        return left

    def _parse_and(self) -> IrExpr:
        left = self._parse_cmp()
        while self._peek().kind is TokKind.KW and self._peek().text == "AND":
            self._advance()
            left = IrExpr(kind="BIN", op="AND", left=left, right=self._parse_cmp())
        return left

    def _parse_cmp(self) -> IrExpr:
        left = self._parse_unary()
        cmp_ops = ("=", "<>", "<", ">", "<=", ">=")
        token = self._peek()
        if token.kind is TokKind.OP and token.text in cmp_ops:
            self._advance()
            right = self._parse_unary()
            return IrExpr(kind="CMP", op=token.text, left=left, right=right)
        return left

    def _parse_unary(self) -> IrExpr:
        token = self._peek()
        if token.kind is TokKind.KW and token.text == "NOT":
            self._advance()
            return IrExpr(kind="NOT", operand=self._parse_unary())
        if token.kind is TokKind.OP and token.text in ("-", "+"):
            self._advance()
            operand = self._parse_unary()
            return IrExpr(kind="NEG" if token.text == "-" else "POS", operand=operand)
        return self._parse_primary()

    def _parse_primary(self) -> IrExpr:
        token = self._advance()
        if token.kind is TokKind.KW and token.text in ("TRUE", "FALSE"):
            return IrExpr(kind="LIT", value=token.text == "TRUE")
        if token.kind is TokKind.NUM:
            return self._parse_number_suffix(token)
        if token.kind is TokKind.STRING_LIT:
            return IrExpr(kind="LIT", value=token.text)
        if token.kind is TokKind.TIME_LIT:
            # lexer keeps the literal text; parse to ms via parser helper
            from plcagent.st.parser import parse_time_ms

            return IrExpr(kind="LIT", value=parse_time_ms(token.text))
        if token.kind is TokKind.IDENT:
            return self._parse_member(token)
        if token.kind is TokKind.OP and token.text == "(":
            inner = self._parse_or()
            self._expect_op(")")
            return inner
        raise SpecExprError(
            f"unexpected token {token.text!r} at position {token.col} in {self._source!r}")

    def _parse_number_suffix(self, token) -> IrExpr:
        text = token.text
        value: float | int
        if text.upper().startswith("16#"):
            value = int(text, 16)
        elif ("." in text) or ("e" in text.lower()):
            value = float(text)
        else:
            value = int(text)
        # 1.5 or 1e3 -> REAL literal; plain int stays int (TIME arrives via TIME_LIT)
        return IrExpr(kind="LIT", value=value)

    def _parse_member(self, token) -> IrExpr:
        # member access arrives as Ident#member thanks to the pre-normalization
        if "__DOT__" in token.text:
            seq_name, member = token.text.split("__DOT__", 1)
            return IrExpr(kind="MEMBER", name=seq_name,
                          right=IrExpr(kind="VAR", name=member))
        return IrExpr(kind="VAR", name=token.text)


def parse_spec_expr(source: str) -> IrExpr:
    """Parse one spec expression into an IrExpr tree; raises SpecExprError."""
    return _ExprParser(source).parse()
