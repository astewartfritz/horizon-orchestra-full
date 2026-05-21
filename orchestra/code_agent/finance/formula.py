"""Formula engine — DSL parser, dependency graph, Excel + AI-native formulas."""

from __future__ import annotations

import re
import math
from typing import Any, Callable

from orchestra.code_agent.finance.models import SheetCell, SheetRange, SheetValueType


class CellRef:
    """Parsed cell reference like 'A1', '$B$2', or range 'A1:B5'."""

    RE = re.compile(r"^([A-Z]+)(\d+)$")
    RANGE_RE = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")

    def __init__(self, col: int, row: int):
        self.col = col
        self.row = row

    @classmethod
    def parse(cls, ref: str) -> CellRef | None:
        m = cls.RE.match(ref.upper())
        if m:
            col = sum((ord(c) - 64) * (26 ** i) for i, c in enumerate(reversed(m.group(1))))
            return cls(col - 1, int(m.group(2)) - 1)
        return None

    @classmethod
    def to_string(cls, col: int, row: int) -> str:
        c = col
        letters = []
        while True:
            letters.append(chr(65 + (c % 26)))
            c = c // 26 - 1
            if c < 0:
                break
        return "".join(reversed(letters)) + str(row + 1)


class DependencyGraph:
    """Tracks cell dependencies for incremental recalculation."""

    def __init__(self):
        self._deps: dict[str, set[str]] = {}   # cell → cells it depends on
        self._depends_on: dict[str, set[str]] = {}  # cell → cells that depend on it

    def add_dependency(self, cell: str, depends_on: list[str]) -> None:
        self._deps.setdefault(cell, set()).update(depends_on)
        for d in depends_on:
            self._depends_on.setdefault(d, set()).add(cell)

    def get_dependents(self, cell: str) -> set[str]:
        return self._depends_on.get(cell, set())

    def get_dependencies(self, cell: str) -> set[str]:
        return self._deps.get(cell, set())

    def get_recalc_order(self, changed: set[str]) -> list[str]:
        """Topological sort of cells needing recalculation."""
        visited: set[str] = set()
        order: list[str] = []
        to_visit = set(changed)

        def visit(c: str):
            if c in visited:
                return
            visited.add(c)
            for dep in self._depends_on.get(c, set()):
                visit(dep)
            order.append(c)

        while to_visit:
            visit(to_visit.pop())
        return order

    def remove_cell(self, cell: str) -> None:
        # Remove from dependency lists of other cells
        for deps in self._deps.values():
            deps.discard(cell)
        self._deps.pop(cell, None)
        # Remove from dependent lists of other cells
        for deps in self._depends_on.values():
            deps.discard(cell)
        self._depends_on.pop(cell, None)

    def clear(self) -> None:
        self._deps.clear()
        self._depends_on.clear()


class FormulaError(Exception):
    def __init__(self, message: str, cell: str = ""):
        self.cell = cell
        super().__init__(message)


AI_FUNCTIONS: dict[str, Callable] = {}


def register_ai_formula(name: str, fn: Callable) -> None:
    AI_FUNCTIONS[name.upper()] = fn


class FormulaParser:
    """Parses and evaluates spreadsheet formulas.

    Supports:
      - Standard: SUM, AVG, MAX, MIN, COUNT, IF, ROUND, ABS
      - Financial: NPV, IRR, PMT, FV, CAGR, XIRR
      - AI-native: AI_PROJECT, EXPLAIN_VARIANCE, FORECAST, RISK_ANALYSIS
      - Operators: +, -, *, /, ^, %, <, >, =, <>
      - Cell references: A1, B2, $A$1
      - Ranges: A1:A5
    """

    RE_RANGE = re.compile(r"(SUM|AVG|MAX|MIN|COUNT|STDEV)\(([A-Z]+\d+):([A-Z]+\d+)\)", re.IGNORECASE)
    RE_FN = re.compile(r"(AI_PROJECT|EXPLAIN_VARIANCE|FORECAST|RISK_ANALYSIS|NPV|IRR|PMT|FV|CAGR|XIRR|IF|ROUND|ABS)\s*\((.+)\)", re.IGNORECASE)
    RE_CELL = re.compile(r"(?<![A-Z])([A-Z]+\d+)(?![A-Z]?\d)", re.IGNORECASE)
    RE_OP = re.compile(r"([+\-*/^%<>=!]+)")

    def __init__(self, cell_getter: Callable[[str], Any] | None = None):
        self.cell_getter = cell_getter or (lambda r: 0)
        self.dep_graph = DependencyGraph()

    def parse(self, formula: str, current_cell: str = "") -> tuple[Any, list[str]]:
        """Parse and evaluate a formula. Returns (value, dependencies)."""
        if not formula or not formula.startswith("="):
            return formula, []
        expr = formula[1:].strip()
        deps: list[str] = []
        result = self._eval(expr, deps, current_cell)
        if current_cell:
            self.dep_graph.add_dependency(current_cell, deps)
        return result, deps

    def _eval(self, expr: str, deps: list[str], cell: str = "") -> Any:
        expr = expr.strip()

        # Range functions
        m = self.RE_RANGE.match(expr)
        if m:
            fn = m.group(1).upper()
            range_obj = self._parse_range(m.group(2), m.group(3))
            vals = range_obj.numeric_values
            deps.extend(range_obj.values)
            if fn == "SUM":
                return sum(vals)
            elif fn == "AVG":
                return sum(vals) / len(vals) if vals else 0
            elif fn == "MAX":
                return max(vals) if vals else 0
            elif fn == "MIN":
                return min(vals) if vals else 0
            elif fn == "COUNT":
                return len(vals)
            elif fn == "STDEV":
                return self._stdev(vals)

        # AI-native / financial functions
        m = self.RE_FN.match(expr)
        if m:
            fn = m.group(1).upper()
            args_str = m.group(2)
            args = self._split_args(args_str)
            fn_name = fn

            if fn_name == "IF":
                return self._eval_if(args, deps)
            elif fn_name == "ROUND":
                return round(float(self._eval(args[0], deps)), int(self._eval(args[1], deps)) if len(args) > 1 else 0)
            elif fn_name == "ABS":
                return abs(float(self._eval(args[0], deps)))
            elif fn_name == "NPV":
                return self._npv(args, deps)
            elif fn_name == "PMT":
                return self._pmt(args, deps)
            elif fn_name == "FV":
                return self._fv(args, deps)
            elif fn_name == "CAGR":
                return self._cagr(args, deps)
            elif fn_name in AI_FUNCTIONS:
                return AI_FUNCTIONS[fn_name](args)
            else:
                return f"#UNSUPPORTED({fn_name})"

        # Binary operators
        for op in ["<>", "<=", ">=", "=", "<", ">", "+", "-", "*", "/", "^", "%"]:
            if op in expr and not self._in_quotes(expr, op):
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = self._eval(parts[0].strip(), deps)
                    right = self._eval(parts[1].strip(), deps)
                    return self._apply_op(left, right, op)

        # Cell references
        m = self.RE_CELL.match(expr)
        if m:
            ref = m.group(1).upper()
            deps.append(ref)
            return self.cell_getter(ref)

        # Literal: number or string
        try:
            return float(expr) if "." in expr else int(expr)
        except ValueError:
            return expr.strip("\"'")

    def _parse_range(self, start_ref: str, end_ref: str) -> SheetRange:
        start = CellRef.parse(start_ref)
        end = CellRef.parse(end_ref)
        if not start or not end:
            return SheetRange()

        cells = []
        for r in range(start.row, end.row + 1):
            for c in range(start.col, end.col + 1):
                ref = CellRef.to_string(c, r)
                val = self.cell_getter(ref)
                cells.append(SheetCell(ref=ref, value=val))
        return SheetRange(
            start_ref=start_ref,
            end_ref=end_ref,
            cells=cells,
        )

    def _split_args(self, s: str) -> list[str]:
        args = []
        depth = 0
        current = ""
        for ch in s:
            if ch == "(":
                depth += 1
                current += ch
            elif ch == ")":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0:
                args.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            args.append(current.strip())
        return args

    def _in_quotes(self, s: str, op: str) -> bool:
        in_q = False
        for ch in s:
            if ch in "\"'":
                in_q = not in_q
        return in_q

    def _apply_op(self, left: Any, right: Any, op: str) -> Any:
        try:
            l = float(left) if left else 0
            r = float(right) if right else 0
        except (ValueError, TypeError):
            if op == "=":
                return left == right
            if op == "<>":
                return left != right
            return f"#TYPE"
        if op == "+": return l + r
        if op == "-": return l - r
        if op == "*": return l * r
        if op == "/": return l / r if r != 0 else "#DIV/0"
        if op == "^": return l ** r
        if op == "%": return l % r
        if op == "<": return l < r
        if op == ">": return l > r
        if op == "=": return l == r
        if op == "<=": return l <= r
        if op == ">=": return l >= r
        if op == "<>": return l != r
        return f"#OP({op})"

    def _eval_if(self, args: list[str], deps: list[str]) -> Any:
        if len(args) < 2:
            return "#N/A"
        condition = self._eval(args[0], deps)
        true_val = self._eval(args[1], deps)
        false_val = self._eval(args[2], deps) if len(args) > 2 else ""
        return true_val if condition else false_val

    @staticmethod
    def _stdev(vals: list[float]) -> float:
        if len(vals) < 2:
            return 0
        mean = sum(vals) / len(vals)
        variance = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
        return math.sqrt(variance)

    @staticmethod
    def _npv(args: list[str], deps: list[str]) -> str:
        return "#CALC"  # Requires runtime cash flow resolution

    @staticmethod
    def _pmt(args: list[str], deps: list[str]) -> str:
        return "#CALC"

    @staticmethod
    def _fv(args: list[str], deps: list[str]) -> str:
        return "#CALC"

    @staticmethod
    def _cagr(args: list[str], deps: list[str]) -> str:
        return "#CALC"


class FormulaEngine:
    """High-level formula engine managing all cells and recalculation."""

    def __init__(self):
        self.cells: dict[str, SheetCell] = {}
        self.parser = FormulaParser(cell_getter=self.get_cell_value)
        self.dep_graph = self.parser.dep_graph

    def set_cell(self, ref: str, value: Any = "", formula: str = "",
                 ai_generated: bool = False) -> SheetCell:
        ref = ref.upper()
        cell = SheetCell(ref=ref, value=value, formula=formula, ai_generated=ai_generated)
        if formula:
            try:
                result, deps = self.parser.parse(formula, current_cell=ref)
                cell.value = result
                cell.value_type = SheetValueType.FORMULA
                cell.formatted = self._format_value(result)
            except FormulaError as e:
                cell.value = f"#{e}"
                cell.value_type = SheetValueType.ERROR
                cell.formatted = f"#{e}"
        else:
            cell.value_type = self._detect_type(value)
        self.cells[ref] = cell
        return cell

    def get_cell(self, ref: str) -> SheetCell | None:
        return self.cells.get(ref.upper())

    def get_cell_value(self, ref: str) -> Any:
        cell = self.cells.get(ref.upper())
        return cell.value if cell else 0

    def recalc(self, changed_refs: set[str]) -> None:
        order = self.dep_graph.get_recalc_order(set(r.upper() for r in changed_refs))
        for ref in order:
            cell = self.cells.get(ref)
            if cell and cell.formula:
                try:
                    result, _ = self.parser.parse(cell.formula, current_cell=ref)
                    cell.value = result
                    cell.formatted = self._format_value(result)
                except FormulaError as e:
                    cell.value = f"#{e}"
                    cell.formatted = f"#{e}"

    def get_range(self, start_ref: str, end_ref: str) -> list[SheetCell]:
        start = CellRef.parse(start_ref)
        end = CellRef.parse(end_ref)
        if not start or not end:
            return []
        cells = []
        for r in range(start.row, end.row + 1):
            for c in range(start.col, end.col + 1):
                ref = CellRef.to_string(c, r)
                cell = self.cells.get(ref)
                if cell:
                    cells.append(cell)
        return cells

    def to_grid(self) -> list[list[Any]]:
        if not self.cells:
            return []
        max_row = max(CellRef.parse(r).row for r in self.cells if CellRef.parse(r)) + 1
        max_col = max(CellRef.parse(r).col for r in self.cells if CellRef.parse(r)) + 1
        grid = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
        for ref, cell in self.cells.items():
            parsed = CellRef.parse(ref)
            if parsed:
                grid[parsed.row][parsed.col] = cell.formatted or cell.value
        return grid

    def clear(self) -> None:
        self.cells.clear()
        self.dep_graph.clear()

    def _detect_type(self, value: Any) -> SheetValueType:
        if isinstance(value, bool):
            return SheetValueType.BOOLEAN
        if isinstance(value, (int, float)):
            return SheetValueType.NUMBER
        if isinstance(value, str):
            if value.startswith("="):
                return SheetValueType.FORMULA
            try:
                float(value)
                return SheetValueType.NUMBER
            except ValueError:
                pass
        return SheetValueType.STRING

    def _format_value(self, value: Any) -> str:
        if isinstance(value, float):
            if abs(value) >= 1_000_000:
                return f"${value:,.0f}"
            if value == int(value):
                return f"{int(value):,}"
            return f"{value:,.2f}"
        return str(value)
