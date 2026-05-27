from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class PortDirection(Enum):
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"


@dataclass
class Port:
    name: str
    direction: PortDirection
    width: int = 1

    def verilog_declaration(self) -> str:
        dir_str = self.direction.value
        width_str = f" [{self.width - 1}:0]" if self.width > 1 else ""
        return f"  {dir_str} [{self.width - 1}:0] {self.name};" if self.width > 1 else f"  {dir_str} {self.name};"


@dataclass
class Wire:
    name: str
    width: int = 1

    def verilog_declaration(self) -> str:
        width_str = f" [{self.width - 1}:0]" if self.width > 1 else ""
        return f"  wire{width_str} {self.name};"


@dataclass
class Register:
    name: str
    width: int = 1
    reset_value: int = 0

    def verilog_declaration(self) -> str:
        width_str = f" [{self.width - 1}:0]" if self.width > 1 else ""
        return f"  reg{width_str} {self.name};"


@dataclass
class Assignment:
    target: str
    expression: str
    is_comb: bool = True
    condition: str | None = None
    comment: str | None = None


@dataclass
class AlwaysBlock:
    sensitivity_list: str
    body: list[str | Assignment]
    block_type: str = "always"

    def render(self, indent: str = "  ") -> str:
        lines = [f"{indent}{self.block_type} @({self.sensitivity_list}) begin"]
        for item in self.body:
            if isinstance(item, Assignment):
                if item.condition:
                    lines.append(f"{indent}    if ({item.condition}) begin")
                    lines.append(f"{indent}      {item.target} <= {item.expression};")
                    lines.append(f"{indent}    end")
                else:
                    op = "=" if item.is_comb else "<="
                    lines.append(f"{indent}    {item.target} {op} {item.expression};")
            else:
                for line in str(item).split("\n"):
                    lines.append(f"{indent}    {line}")
        lines.append(f"{indent}end")
        return "\n".join(lines)


@dataclass
class Module:
    name: str
    ports: list[Port] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    registers: list[Register] = field(default_factory=list)
    always_blocks: list[AlwaysBlock] = field(default_factory=list)
    assign_statements: list[Assignment] = field(default_factory=list)
    submodules: list[tuple[str, str]] = field(default_factory=list)  # (instance_name, module_name)
    params: dict[str, int | str] = field(default_factory=dict)
    comment: str | None = None

    def add_port(self, name: str, direction: PortDirection, width: int = 1) -> Port:
        p = Port(name=name, direction=direction, width=width)
        self.ports.append(p)
        return p

    def add_wire(self, name: str, width: int = 1) -> Wire:
        w = Wire(name=name, width=width)
        self.wires.append(w)
        return w

    def add_register(self, name: str, width: int = 1, reset_value: int = 0) -> Register:
        r = Register(name=name, width=width, reset_value=reset_value)
        self.registers.append(r)
        return r

    def add_always(self, sensitivity: str, body: list[str | Assignment],
                   block_type: str = "always") -> AlwaysBlock:
        block = AlwaysBlock(sensitivity_list=sensitivity, body=body, block_type=block_type)
        self.always_blocks.append(block)
        return block

    def add_assign(self, target: str, expression: str, comment: str | None = None) -> Assignment:
        a = Assignment(target=target, expression=expression, comment=comment)
        self.assign_statements.append(a)
        return a

    def add_submodule(self, instance_name: str, module_name: str) -> None:
        self.submodules.append((instance_name, module_name))

    def render_verilog(self) -> str:
        lines = [f"module {self.name} ("]
        if self.params:
            lines.insert(0, f"// {self.comment}" if self.comment else "")
            param_lines = []
            for k, v in self.params.items():
                param_lines.append(f"    parameter {k} = {v}")
            param_str = " #(\n" + ",\n".join(param_lines) + "\n)"
        else:
            param_str = ""

        for i, port in enumerate(self.ports):
            comma = "," if i < len(self.ports) - 1 else ""
            width_str = f" [{port.width - 1}:0]" if port.width > 1 else ""
            lines.append(f"  {port.direction.value}{width_str} {port.name}{comma}")
        lines.append(");\n")

        for r in self.registers:
            lines.append(r.verilog_declaration())
        for w in self.wires:
            lines.append(w.verilog_declaration())

        lines.append("")
        for a in self.assign_statements:
            c = f"  // {a.comment}" if a.comment else ""
            lines.append(c)
            lines.append(f"  assign {a.target} = {a.expression};")

        for block in self.always_blocks:
            lines.append("")
            lines.append(block.render())

        for instance, mod in self.submodules:
            lines.append(f"  {mod} {instance} ();")

        lines.append(f"\nendmodule")
        return "\n".join(lines)


@dataclass
class RTLSpec:
    name: str
    description: str
    modules: list[Module] = field(default_factory=list)
    top_module: str = "cpu_core"
    datapath_width: int = 32
    version: str = "1.0.0"

    def add_module(self, module: Module) -> None:
        self.modules.append(module)

    def render_all(self) -> dict[str, str]:
        return {m.name: m.render_verilog() for m in self.modules}

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "modules": len(self.modules),
            "top": self.top_module,
            "datapath_width": self.datapath_width,
        }
