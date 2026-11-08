"""Recursive-descent parser for the ST subset.

Operator precedence (low to high): OR, XOR, AND, comparison, +-, * / MOD,
unary. Booleans are NOT short-circuited (15.1: full evaluation).
"""

from __future__ import annotations

import re

from plcagent.st.ast_nodes import (
    Assignment,
    Binary,
    CaseArm,
    CaseStatement,
    ForStatement,
    IfStatement,
    Literal,
    Pou,
    ReturnStatement,
    Unary,
    VarDecl,
    VarRef,
    WhileStatement,
)
from plcagent.st.lexer import StSyntaxError, Token, TokKind, tokenize
from plcagent.st.types import BOOL, BY_NAME, DINT, TIME

_TIME_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|d|h|m|s)")
_TIME_FACTOR = {"d": 86_400_000, "h": 3_600_000, "m": 60_000, "s": 1000, "ms": 1}


def parse_time_ms(text: str) -> int:
    """T#2s / T#3500ms / TIME#1m30s -> whole milliseconds (floor, 15.1)."""
    body = text.split("#", 1)[1].lower().replace("_", "")
    total_ms = 0
    consumed = 0
    for match in _TIME_PART.finditer(body):
        consumed += len(match.group(0))
        total_ms += int(float(match.group(1)) * _TIME_FACTOR[match.group(2)])
    if consumed != len(body):
        raise ValueError(f"bad TIME literal {text!r}")
    return total_ms


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # -- token helpers ------------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind is not TokKind.EOF:
            self.pos += 1
        return tok

    def skip_newlines(self) -> None:
        while self.peek().kind is TokKind.NEWLINE:
            self.advance()

    def at_op(self, text: str) -> bool:
        tok = self.peek()
        return tok.kind is TokKind.OP and tok.text == text

    def at_kw(self, word: str) -> bool:
        tok = self.peek()
        return tok.kind is TokKind.KW and tok.text.upper() == word

    def expect_op(self, text: str) -> Token:
        if self.at_op(text):
            return self.advance()
        raise self._error(f"expected {text!r}")

    def expect_kw(self, word: str) -> Token:
        if self.at_kw(word):
            return self.advance()
        raise self._error(f"expected {word}")

    def _error(self, message: str) -> StSyntaxError:
        tok = self.peek()
        return StSyntaxError(message, tok.line, tok.col)

    # -- entry point ---------------------------------------------------------
    def parse_pou(self) -> Pou:
        self.skip_newlines()
        if self.at_kw("PROGRAM"):
            self.advance()
            pou_type = "program"
        elif self.at_kw("FUNCTION_BLOCK"):
            self.advance()
            pou_type = "function_block"
        else:
            raise self._error("expected PROGRAM or FUNCTION_BLOCK")
        name = self.advance()
        if name.kind is not TokKind.IDENT:
            raise self._error("expected POU name")
        decls = self._parse_var_sections()
        body = self._parse_statement_block(("END_PROGRAM", "END_FUNCTION_BLOCK"))
        self.advance()  # consume END_PROGRAM / END_FUNCTION_BLOCK
        return Pou(name=name.text, pou_type=pou_type, decls=tuple(decls), body=tuple(body))

    # -- declarations ---------------------------------------------------------
    def _parse_var_sections(self) -> list[VarDecl]:
        decls: list[VarDecl] = []
        while True:
            self.skip_newlines()
            if not (self.at_kw("VAR") or self.at_kw("VAR_INPUT") or self.at_kw("VAR_OUTPUT")):
                return decls
            header = self.advance()
            direction = {"VAR": "local", "VAR_INPUT": "input", "VAR_OUTPUT": "output"}[
                header.text.upper()]
            while not self.at_kw("END_VAR"):
                self.skip_newlines()
                if self.at_kw("END_VAR"):
                    break
                decls.extend(self._parse_one_decl(direction))
            self.expect_kw("END_VAR")

    def _parse_one_decl(self, direction: str) -> list[VarDecl]:
        names: list[str] = []
        while True:
            tok = self.advance()
            if tok.kind is not TokKind.IDENT:
                raise self._error("expected variable name")
            names.append(tok.text)
            if self.at_op(","):
                self.advance()
                continue
            break
        self.expect_op(":")
        type_tok = self.advance()
        if type_tok.kind is TokKind.KW and type_tok.text.upper() in BY_NAME:
            st_type = BY_NAME[type_tok.text.upper()]
        else:
            raise self._error("expected type name")
        init: object = None
        if self.at_op(":="):
            self.advance()
            init = self._parse_expr()
        self.expect_op(";")
        return [VarDecl(name=name, st_type=st_type, init=init, direction=direction)
                for name in names]

    # -- statements -------------------------------------------------------------
    def _parse_statement_block(self, stop_words: tuple[str, ...],
                               stop_pred=None) -> list:
        stmts: list = []
        while True:
            self.skip_newlines()
            tok = self.peek()
            if tok.kind is TokKind.EOF:
                raise self._error("unexpected end of file")
            if tok.kind is TokKind.KW and tok.text.upper() in stop_words:
                return stmts
            if stop_pred is not None and stop_pred(self):
                return stmts
            stmts.append(self._parse_statement())

    def _parse_statement(self) -> object:
        tok = self.peek()
        if tok.kind is TokKind.KW:
            word = tok.text.upper()
            if word == "IF":
                return self._parse_if()
            if word == "CASE":
                return self._parse_case()
            if word == "FOR":
                return self._parse_for()
            if word == "WHILE":
                return self._parse_while()
            if word == "RETURN":
                self.advance()
                self.expect_op(";")
                return ReturnStatement()
        return self._parse_assignment()

    def _parse_assignment(self) -> Assignment:
        target = self.advance()
        if target.kind is not TokKind.IDENT:
            raise self._error("expected identifier in assignment")
        self.expect_op(":=")
        expr = self._parse_expr()
        self.expect_op(";")
        return Assignment(target=target.text, expr=expr)

    def _parse_if(self) -> IfStatement:
        self.expect_kw("IF")
        branches: list[tuple[object, tuple]] = []
        cond = self._parse_expr()
        self.expect_kw("THEN")
        branch_stops = ("ELSIF", "ELSE", "END_IF")
        branches.append((cond, tuple(self._parse_statement_block(branch_stops))))
        while self.at_kw("ELSIF"):
            self.advance()
            cond = self._parse_expr()
            self.expect_kw("THEN")
            branches.append((cond, tuple(self._parse_statement_block(branch_stops))))
        else_body: tuple = ()
        if self.at_kw("ELSE"):
            self.advance()
            else_body = tuple(self._parse_statement_block(("END_IF",)))
        self.expect_kw("END_IF")
        self.expect_op(";")
        return IfStatement(branches=tuple(branches), else_body=else_body)

    @staticmethod
    def _at_next_case_label(parser: Parser) -> bool:
        """A CASE arm body ends where the next integer label group begins."""
        tok = parser.peek()
        return (tok.kind is TokKind.NUM
                and parser.peek(1).kind is TokKind.OP
                and parser.peek(1).text in (":", ","))

    def _parse_case(self) -> CaseStatement:
        self.expect_kw("CASE")
        selector = self._parse_expr()
        self.expect_kw("OF")
        arm_stops = ("END_CASE", "ELSE")
        arms: list[CaseArm] = []
        else_body: tuple = ()
        while True:
            self.skip_newlines()
            if self.at_kw("END_CASE"):
                break
            if self.at_kw("ELSE"):  # IEC ST: CASE else has no trailing colon
                self.advance()
                else_body = tuple(self._parse_statement_block(("END_CASE",)))
                break
            labels: list[int] = []
            while True:
                tok = self.advance()
                if tok.kind is not TokKind.NUM:
                    raise self._error("expected integer case label")
                labels.append(int(tok.text))
                if self.at_op(","):
                    self.advance()
                    continue
                break
            self.expect_op(":")
            arms.append(CaseArm(
                labels=tuple(labels),
                body=tuple(self._parse_statement_block(arm_stops,
                                                       stop_pred=self._at_next_case_label)),
            ))
        self.expect_kw("END_CASE")
        self.expect_op(";")
        return CaseStatement(selector=selector, arms=tuple(arms), else_body=else_body)

    def _parse_for(self) -> ForStatement:
        self.expect_kw("FOR")
        var_tok = self.advance()
        if var_tok.kind is not TokKind.IDENT:
            raise self._error("expected loop variable")
        self.expect_op(":=")
        start = self._parse_expr()
        self.expect_kw("TO")
        stop = self._parse_expr()
        step = None
        if self.at_kw("BY"):
            self.advance()
            step = self._parse_expr()
        self.expect_kw("DO")
        body = tuple(self._parse_statement_block(("END_FOR",)))
        self.expect_kw("END_FOR")
        self.expect_op(";")
        return ForStatement(loop_var=var_tok.text, start=start, stop=stop,
                            step=step, body=body)

    def _parse_while(self) -> WhileStatement:
        self.expect_kw("WHILE")
        cond = self._parse_expr()
        self.expect_kw("DO")
        body = tuple(self._parse_statement_block(("END_WHILE",)))
        self.expect_kw("END_WHILE")
        self.expect_op(";")
        return WhileStatement(cond=cond, body=body)

    # -- expressions ----------------------------------------------------------
    def _parse_expr(self) -> object:
        return self._parse_or()

    def _parse_or(self) -> object:
        left = self._parse_xor()
        while self.at_kw("OR"):
            self.advance()
            left = Binary("OR", left, self._parse_xor())
        return left

    def _parse_xor(self) -> object:
        left = self._parse_and()
        while self.at_kw("XOR"):
            self.advance()
            left = Binary("XOR", left, self._parse_and())
        return left

    def _parse_and(self) -> object:
        left = self._parse_cmp()
        while self.at_kw("AND") or self.at_op("&"):
            self.advance()
            left = Binary("AND", left, self._parse_cmp())
        return left

    _CMP_OPS = ("=", "<>", "<", ">", "<=", ">=")

    def _parse_cmp(self) -> object:
        left = self._parse_add()
        while self.peek().kind is TokKind.OP and self.peek().text in self._CMP_OPS:
            op = self.advance().text
            left = Binary(op, left, self._parse_add())
        return left

    def _parse_add(self) -> object:
        left = self._parse_mul()
        while self.at_op("+") or self.at_op("-"):
            op = self.advance().text
            left = Binary(op, left, self._parse_mul())
        return left

    def _parse_mul(self) -> object:
        left = self._parse_unary()
        while self.at_op("*") or self.at_op("/") or self.at_kw("MOD"):
            op = self.advance().text
            left = Binary(op.upper(), left, self._parse_unary())
        return left

    def _parse_unary(self) -> object:
        if self.at_op("-"):
            self.advance()
            return Unary("-", self._parse_unary())
        if self.at_kw("NOT"):
            self.advance()
            return Unary("NOT", self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> object:
        tok = self.advance()
        if tok.kind is TokKind.IDENT:
            return VarRef(tok.text)
        if tok.kind is TokKind.KW and tok.text.upper() in ("TRUE", "FALSE"):
            return Literal(BOOL, tok.text.upper() == "TRUE")
        if tok.kind is TokKind.NUM:
            return self._number_literal(tok)
        if tok.kind is TokKind.TIME_LIT:
            return Literal(TIME, parse_time_ms(tok.text))
        if tok.kind is TokKind.STRING_LIT:
            from plcagent.st.types import STRING
            return Literal(STRING, tok.text)
        if self.at_op(")"):
            pass
        if tok.kind is TokKind.OP and tok.text == "(":
            inner = self._parse_expr()
            self.expect_op(")")
            return inner
        raise self._error("unexpected token in expression")

    def _number_literal(self, tok: Token) -> Literal:
        text = tok.text
        if "." in text or "e" in text.lower():
            from plcagent.st.types import REAL
            return Literal(REAL, float(text))
        for prefix in ("DINT#", "INT#", "BOOL#"):
            if text.upper().startswith(prefix):
                plain = text.split("#", 1)[1]
                st_type = BY_NAME[prefix[:-1]]
                value = plain.upper() in ("TRUE", "1") if st_type is BOOL else int(plain)
                return Literal(st_type, value)
        return Literal(DINT, int(text))


def parse_program(source: str) -> Pou:
    return Parser(tokenize(source)).parse_pou()
