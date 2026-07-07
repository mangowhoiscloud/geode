"""Deterministic math calculation tools."""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from math import isqrt
from typing import Any

from core.tools.base import tool_error

_MAX_EXPRESSION_CHARS = 500
_MAX_AST_NODES = 160
_MAX_PRECISION = 100
_DEFAULT_PRECISION = 50
_MAX_LITERAL_DIGITS = 120
_MAX_LITERAL_MAGNITUDE = 1000
_MAX_POWER_ABS = 1000
_MAX_FRACTION_DIGITS = 4000
_VALIDATION_HINT = "Use numeric literals, parentheses, +, -, *, /, //, %, **, abs(), or sqrt()."


@dataclass(frozen=True, slots=True)
class _MathValue:
    value: Fraction | Decimal
    exact: bool


class _CalculationError(ValueError):
    """Invalid or unsupported calculator input."""


class CalculateTool:
    """Evaluate bounded arithmetic without shelling out or parsing with eval."""

    @property
    def name(self) -> str:
        return "calculate"

    @property
    def description(self) -> str:
        return (
            "Compute bounded arithmetic exactly-first. Use for deterministic numeric "
            "calculation; supports +, -, *, /, //, %, **, parentheses, abs(), and sqrt()."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression to evaluate, e.g. '(2 + 3) / 7'.",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_PRECISION,
                    "description": "Decimal digits for approximate output. Default 50.",
                },
            },
            "required": ["expression"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        return self._execute_sync(**kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        expression = str(kwargs.get("expression") or "").strip()
        try:
            precision = _coerce_precision(kwargs.get("precision", _DEFAULT_PRECISION))
            result = _evaluate_expression(expression, precision=precision)
        except _CalculationError as exc:
            return tool_error(
                str(exc),
                error_type="validation",
                recoverable=True,
                hint=_VALIDATION_HINT,
            )

        decimal_value = _decimal_string(result.value, precision)
        payload: dict[str, Any] = {
            "status": "ok",
            "expression": expression,
            "value": _primary_value(result, decimal_value),
            "decimal": decimal_value,
            "exact": result.exact,
            "precision": precision,
            "engine": "geode_fraction_ast",
        }
        if isinstance(result.value, Fraction):
            payload["fraction"] = _fraction_string(result.value)
        else:
            payload["note"] = "Approximate decimal result; exact rational form is unavailable."
        return {"result": payload}


def _coerce_precision(raw: Any) -> int:
    try:
        precision = int(raw)
    except (TypeError, ValueError) as exc:
        raise _CalculationError("precision must be an integer") from exc
    if not 1 <= precision <= _MAX_PRECISION:
        raise _CalculationError(f"precision must be between 1 and {_MAX_PRECISION}")
    return precision


def _evaluate_expression(expression: str, *, precision: int) -> _MathValue:
    if not expression:
        raise _CalculationError("expression is required")
    if len(expression) > _MAX_EXPRESSION_CHARS:
        raise _CalculationError(f"expression exceeds {_MAX_EXPRESSION_CHARS} characters")

    try:
        wrapped = _wrap_number_tokens(expression)
        tree = ast.parse(wrapped, mode="eval")
    except (SyntaxError, tokenize.TokenError, IndentationError) as exc:
        raise _CalculationError("expression is not valid arithmetic syntax") from exc

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > _MAX_AST_NODES:
        raise _CalculationError(f"expression is too complex ({node_count} AST nodes)")
    return _eval_node(tree.body, precision=precision)


def _wrap_number_tokens(expression: str) -> str:
    tokens: list[tuple[int, str]] = []
    stream = io.StringIO(expression).readline
    for token in tokenize.generate_tokens(stream):
        if token.type == tokenize.NUMBER:
            tokens.extend(
                [
                    (tokenize.NAME, "_F"),
                    (tokenize.OP, "("),
                    (tokenize.STRING, repr(token.string)),
                    (tokenize.OP, ")"),
                ]
            )
        else:
            tokens.append((token.type, token.string))
    return tokenize.untokenize(tokens)


def _eval_node(node: ast.AST, *, precision: int) -> _MathValue:
    if isinstance(node, ast.Call):
        return _eval_call(node, precision=precision)
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, precision=precision)
        right = _eval_node(node.right, precision=precision)
        return _eval_binop(node.op, left, right, precision=precision)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, precision=precision)
        return _eval_unaryop(node.op, operand)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return _MathValue(Fraction(node.value), exact=True)
    raise _CalculationError(f"unsupported syntax: {type(node).__name__}")


def _eval_call(node: ast.Call, *, precision: int) -> _MathValue:
    if not isinstance(node.func, ast.Name):
        raise _CalculationError("only direct function calls are supported")
    name = node.func.id
    if name == "_F":
        if len(node.args) != 1 or node.keywords:
            raise _CalculationError("invalid numeric literal")
        literal = node.args[0]
        if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
            raise _CalculationError("invalid numeric literal")
        return _MathValue(_fraction_from_literal(literal.value), exact=True)
    if name == "abs":
        if len(node.args) != 1 or node.keywords:
            raise _CalculationError("abs() takes one argument")
        value = _eval_node(node.args[0], precision=precision)
        return _MathValue(-value.value if value.value < 0 else value.value, exact=value.exact)
    if name == "sqrt":
        if len(node.args) != 1 or node.keywords:
            raise _CalculationError("sqrt() takes one argument")
        return _sqrt(_eval_node(node.args[0], precision=precision), precision=precision)
    raise _CalculationError(f"unsupported function: {name}")


def _fraction_from_literal(literal: str) -> Fraction:
    try:
        value = Decimal(literal)
    except InvalidOperation as exc:
        raise _CalculationError(f"invalid numeric literal: {literal}") from exc
    if not value.is_finite():
        raise _CalculationError("numeric literal must be finite")
    digits = value.as_tuple().digits
    if len(digits) > _MAX_LITERAL_DIGITS or abs(value.adjusted()) > _MAX_LITERAL_MAGNITUDE:
        raise _CalculationError("numeric literal is too large")
    return _check_fraction_size(Fraction(value))


def _eval_unaryop(op: ast.unaryop, operand: _MathValue) -> _MathValue:
    if isinstance(op, ast.UAdd):
        return operand
    if isinstance(op, ast.USub):
        return _MathValue(-operand.value, exact=operand.exact)
    raise _CalculationError(f"unsupported unary operator: {type(op).__name__}")


def _eval_binop(
    op: ast.operator,
    left: _MathValue,
    right: _MathValue,
    *,
    precision: int,
) -> _MathValue:
    if isinstance(op, ast.Add):
        return _combine(left, right, lambda a, b: a + b, precision=precision)
    if isinstance(op, ast.Sub):
        return _combine(left, right, lambda a, b: a - b, precision=precision)
    if isinstance(op, ast.Mult):
        return _combine(left, right, lambda a, b: a * b, precision=precision)
    if isinstance(op, ast.Div):
        return _divide(left, right, precision=precision)
    if isinstance(op, ast.FloorDiv):
        return _floor_divide(left, right, precision=precision)
    if isinstance(op, ast.Mod):
        return _modulo(left, right, precision=precision)
    if isinstance(op, ast.Pow):
        return _power(left, right, precision=precision)
    raise _CalculationError(f"unsupported operator: {type(op).__name__}")


def _combine(
    left: _MathValue,
    right: _MathValue,
    operation: Any,
    *,
    precision: int,
) -> _MathValue:
    if isinstance(left.value, Fraction) and isinstance(right.value, Fraction):
        return _MathValue(_check_fraction_size(operation(left.value, right.value)), exact=True)
    with localcontext() as ctx:
        ctx.prec = precision
        return _MathValue(
            operation(_to_decimal(left.value, precision), _to_decimal(right.value, precision)),
            exact=False,
        )


def _divide(left: _MathValue, right: _MathValue, *, precision: int) -> _MathValue:
    if right.value == 0:
        raise _CalculationError("division by zero")
    return _combine(left, right, lambda a, b: a / b, precision=precision)


def _floor_divide(left: _MathValue, right: _MathValue, *, precision: int) -> _MathValue:
    if right.value == 0:
        raise _CalculationError("division by zero")
    return _combine(left, right, lambda a, b: Fraction(a // b), precision=precision)


def _modulo(left: _MathValue, right: _MathValue, *, precision: int) -> _MathValue:
    if right.value == 0:
        raise _CalculationError("modulo by zero")
    return _combine(left, right, lambda a, b: a % b, precision=precision)


def _power(left: _MathValue, right: _MathValue, *, precision: int) -> _MathValue:
    if not isinstance(right.value, Fraction) or right.value.denominator != 1:
        raise _CalculationError("exponent must be an integer")
    exponent = right.value.numerator
    if abs(exponent) > _MAX_POWER_ABS:
        raise _CalculationError(f"absolute exponent must be <= {_MAX_POWER_ABS}")
    if isinstance(left.value, Fraction):
        if left.value == 0 and exponent < 0:
            raise _CalculationError("zero cannot be raised to a negative power")
        return _MathValue(_check_fraction_size(left.value**exponent), exact=left.exact)
    with localcontext() as ctx:
        ctx.prec = precision
        return _MathValue(left.value**exponent, exact=False)


def _sqrt(value: _MathValue, *, precision: int) -> _MathValue:
    if value.value < 0:
        raise _CalculationError("sqrt() is only defined for non-negative values")
    if isinstance(value.value, Fraction):
        numerator_root = isqrt(value.value.numerator)
        denominator_root = isqrt(value.value.denominator)
        if (
            numerator_root * numerator_root == value.value.numerator
            and denominator_root * denominator_root == value.value.denominator
        ):
            return _MathValue(Fraction(numerator_root, denominator_root), exact=value.exact)
    with localcontext() as ctx:
        ctx.prec = precision
        return _MathValue(_to_decimal(value.value, precision).sqrt(), exact=False)


def _to_decimal(value: Fraction | Decimal, precision: int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    with localcontext() as ctx:
        ctx.prec = precision
        return Decimal(value.numerator) / Decimal(value.denominator)


def _check_fraction_size(value: Fraction) -> Fraction:
    numerator_digits = len(str(abs(value.numerator)))
    denominator_digits = len(str(value.denominator))
    if max(numerator_digits, denominator_digits) > _MAX_FRACTION_DIGITS:
        raise _CalculationError("result is too large")
    return value


def _fraction_string(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _decimal_string(value: Fraction | Decimal, precision: int) -> str:
    with localcontext() as ctx:
        ctx.prec = precision
        decimal_value = _to_decimal(value, precision)
        rendered = format(+decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _primary_value(result: _MathValue, decimal_value: str) -> str:
    if isinstance(result.value, Fraction):
        return _fraction_string(result.value)
    return decimal_value
