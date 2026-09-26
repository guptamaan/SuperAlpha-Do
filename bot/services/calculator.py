"""Safe arithmetic evaluation (whitelisted AST walk) for the ``calc`` command."""

from __future__ import annotations

import ast
import re
from typing import Any

_ALLOWED_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARYOPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def _safe_eval_math_expression(expression: str) -> float | int:
    expr = expression.strip()
    if not re.fullmatch(r"[0-9+\-*/(). %^\s]+", expr):
        raise ValueError("invalid expression characters")
    expr = expr.replace("^", "**")
    tree = ast.parse(expr, mode="eval")

    def eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
            return _ALLOWED_UNARYOPS[type(node.op)](eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](eval_node(node.left), eval_node(node.right))
        raise ValueError("unsupported expression")

    return eval_node(tree)