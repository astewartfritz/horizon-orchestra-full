from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class InstructionFormat(Enum):
    R_TYPE = auto()
    I_TYPE = auto()
    S_TYPE = auto()
    B_TYPE = auto()
    U_TYPE = auto()
    J_TYPE = auto()


class Opcode(Enum):
    # Integer operations
    ADD = ("add", InstructionFormat.R_TYPE)
    SUB = ("sub", InstructionFormat.R_TYPE)
    AND = ("and_", InstructionFormat.R_TYPE)
    OR = ("or_", InstructionFormat.R_TYPE)
    XOR = ("xor_", InstructionFormat.R_TYPE)
    SLL = ("sll", InstructionFormat.R_TYPE)
    SRL = ("srl", InstructionFormat.R_TYPE)
    SRA = ("sra", InstructionFormat.R_TYPE)
    SLT = ("slt", InstructionFormat.R_TYPE)
    SLTU = ("sltu", InstructionFormat.R_TYPE)
    MUL = ("mul", InstructionFormat.R_TYPE)
    DIV = ("div", InstructionFormat.R_TYPE)
    REM = ("rem", InstructionFormat.R_TYPE)

    # Immediate operations
    ADDI = ("addi", InstructionFormat.I_TYPE)
    ANDI = ("andi", InstructionFormat.I_TYPE)
    ORI = ("ori", InstructionFormat.I_TYPE)
    XORI = ("xori", InstructionFormat.I_TYPE)
    SLLI = ("slli", InstructionFormat.I_TYPE)
    SRLI = ("srli", InstructionFormat.I_TYPE)
    SRAI = ("srai", InstructionFormat.I_TYPE)
    SLTI = ("slti", InstructionFormat.I_TYPE)
    SLTIU = ("sltiu", InstructionFormat.I_TYPE)

    # Load / Store
    LW = ("lw", InstructionFormat.I_TYPE)
    LH = ("lh", InstructionFormat.I_TYPE)
    LB = ("lb", InstructionFormat.I_TYPE)
    SW = ("sw", InstructionFormat.S_TYPE)
    SH = ("sh", InstructionFormat.S_TYPE)
    SB = ("sb", InstructionFormat.S_TYPE)

    # Branches
    BEQ = ("beq", InstructionFormat.B_TYPE)
    BNE = ("bne", InstructionFormat.B_TYPE)
    BLT = ("blt", InstructionFormat.B_TYPE)
    BGE = ("bge", InstructionFormat.B_TYPE)
    BLTU = ("bltu", InstructionFormat.B_TYPE)
    BGEU = ("bgeu", InstructionFormat.B_TYPE)

    # Upper immediates
    LUI = ("lui", InstructionFormat.U_TYPE)
    AUIPC = ("auipc", InstructionFormat.U_TYPE)

    # Jump
    JAL = ("jal", InstructionFormat.J_TYPE)
    JALR = ("jalr", InstructionFormat.I_TYPE)

    # CSR
    CSRRW = ("csrrw", InstructionFormat.I_TYPE)
    CSRRS = ("csrrs", InstructionFormat.I_TYPE)

    # Custom extensions
    CUSTOM_0 = ("custom0", InstructionFormat.R_TYPE)
    CUSTOM_1 = ("custom1", InstructionFormat.R_TYPE)
    CUSTOM_2 = ("custom2", InstructionFormat.R_TYPE)

    def __init__(self, mnemonic: str, fmt: InstructionFormat):
        self._mnemonic = mnemonic
        self._fmt = fmt

    @property
    def mnemonic(self) -> str:
        return self._mnemonic

    @property
    def fmt(self) -> InstructionFormat:
        return self._fmt

    def is_r_type(self) -> bool:
        return self._fmt == InstructionFormat.R_TYPE

    def is_i_type(self) -> bool:
        return self._fmt == InstructionFormat.I_TYPE

    def is_s_type(self) -> bool:
        return self._fmt == InstructionFormat.S_TYPE

    def is_b_type(self) -> bool:
        return self._fmt == InstructionFormat.B_TYPE

    def is_load_store(self) -> bool:
        return self in {Opcode.LW, Opcode.LH, Opcode.LB, Opcode.SW, Opcode.SH, Opcode.SB}

    def is_branch(self) -> bool:
        return self._fmt == InstructionFormat.B_TYPE


@dataclass(frozen=True)
class Register:
    name: str
    number: int

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class RegisterConvention:
    """ABI register naming and usage conventions."""
    zero: Register = field(default_factory=lambda: Register("zero", 0))
    ra: Register = field(default_factory=lambda: Register("ra", 1))
    sp: Register = field(default_factory=lambda: Register("sp", 2))
    gp: Register = field(default_factory=lambda: Register("gp", 3))
    tp: Register = field(default_factory=lambda: Register("tp", 4))
    t0: Register = field(default_factory=lambda: Register("t0", 5))
    t1: Register = field(default_factory=lambda: Register("t1", 6))
    t2: Register = field(default_factory=lambda: Register("t2", 7))
    s0_fp: Register = field(default_factory=lambda: Register("s0/fp", 8))
    s1: Register = field(default_factory=lambda: Register("s1", 9))
    a0: Register = field(default_factory=lambda: Register("a0", 10))
    a1: Register = field(default_factory=lambda: Register("a1", 11))
    a2: Register = field(default_factory=lambda: Register("a2", 12))
    a3: Register = field(default_factory=lambda: Register("a3", 13))
    a4: Register = field(default_factory=lambda: Register("a4", 14))
    a5: Register = field(default_factory=lambda: Register("a5", 15))
    a6: Register = field(default_factory=lambda: Register("a6", 16))
    a7: Register = field(default_factory=lambda: Register("a7", 17))
    s2: Register = field(default_factory=lambda: Register("s2", 18))
    s3: Register = field(default_factory=lambda: Register("s3", 19))
    s4: Register = field(default_factory=lambda: Register("s4", 20))
    s5: Register = field(default_factory=lambda: Register("s5", 21))
    s6: Register = field(default_factory=lambda: Register("s6", 22))
    s7: Register = field(default_factory=lambda: Register("s7", 23))
    s8: Register = field(default_factory=lambda: Register("s8", 24))
    s9: Register = field(default_factory=lambda: Register("s9", 25))
    s10: Register = field(default_factory=lambda: Register("s10", 26))
    s11: Register = field(default_factory=lambda: Register("s11", 27))
    t3: Register = field(default_factory=lambda: Register("t3", 28))
    t4: Register = field(default_factory=lambda: Register("t4", 29))
    t5: Register = field(default_factory=lambda: Register("t5", 30))
    t6: Register = field(default_factory=lambda: Register("t6", 31))

    def by_number(self, num: int) -> Register:
        for reg in self.__dict__.values():
            if isinstance(reg, Register) and reg.number == num:
                return reg
        raise KeyError(f"No register with number {num}")

    def by_name(self, name: str) -> Register:
        for reg_name, reg in self.__dict__.items():
            if isinstance(reg, Register) and reg.name == name:
                return reg
        raise KeyError(f"No register named {name}")

    def caller_saved(self) -> list[Register]:
        return [self.ra, self.t0, self.t1, self.t2, self.t3, self.t4, self.t5, self.t6,
                self.a0, self.a1, self.a2, self.a3, self.a4, self.a5, self.a6, self.a7]

    def callee_saved(self) -> list[Register]:
        return [self.s0_fp, self.s1, self.s2, self.s3, self.s4, self.s5,
                self.s6, self.s7, self.s8, self.s9, self.s10, self.s11]


@dataclass
class Instruction:
    opcode: Opcode
    rd: int | None = None
    rs1: int | None = None
    rs2: int | None = None
    imm: int = 0
    funct3: int = 0
    funct7: int = 0

    def encode(self) -> int:
        opcode_val = _opcode_bits(self.opcode)
        match self.opcode.fmt:
            case InstructionFormat.R_TYPE:
                return (
                    (self.funct7 << 25)
                    | (self.rs2 << 20)
                    | (self.rs1 << 15)
                    | (self.funct3 << 12)
                    | (self.rd << 7)
                    | opcode_val
                )
            case InstructionFormat.I_TYPE:
                imm12 = self.imm & 0xFFF
                return (
                    (imm12 << 20)
                    | (self.rs1 << 15)
                    | (self.funct3 << 12)
                    | (self.rd << 7)
                    | opcode_val
                )
            case InstructionFormat.S_TYPE:
                imm12 = self.imm & 0xFFF
                return (
                    ((imm12 >> 5) << 25)
                    | (self.rs2 << 20)
                    | (self.rs1 << 15)
                    | (self.funct3 << 12)
                    | ((imm12 & 0x1F) << 7)
                    | opcode_val
                )
            case InstructionFormat.B_TYPE:
                imm13 = self.imm & 0x1FFF
                return (
                    ((imm13 >> 12) << 31)
                    | (((imm13 >> 5) & 0x3F) << 25)
                    | (self.rs2 << 20)
                    | (self.rs1 << 15)
                    | (self.funct3 << 12)
                    | (((imm13 >> 1) & 0xF) << 8)
                    | ((imm13 >> 11) & 1) << 7
                    | opcode_val
                )
            case InstructionFormat.U_TYPE:
                imm20 = self.imm & 0xFFFFF
                return (imm20 << 12) | (self.rd << 7) | opcode_val
            case InstructionFormat.J_TYPE:
                imm21 = self.imm & 0x1FFFFF
                return (
                    ((imm21 >> 20) << 31)
                    | (((imm21 >> 1) & 0x3FF) << 21)
                    | (((imm21 >> 11) & 1) << 20)
                    | (((imm21 >> 12) & 0xFF) << 12)
                    | (self.rd << 7)
                    | opcode_val
                )

    def disassemble(self) -> str:
        parts = [self.opcode.mnemonic]
        if self.rd is not None:
            parts.append(f"x{self.rd}")
        if self.rs1 is not None:
            parts.append(f"x{self.rs1}")
        if self.rs2 is not None:
            parts.append(f"x{self.rs2}")
        if self.imm:
            if self.opcode.fmt in (InstructionFormat.U_TYPE, InstructionFormat.J_TYPE):
                parts.append(f"0x{self.imm:x}")
            else:
                parts.append(f"{self.imm}")
        return " ".join(parts)


def _opcode_bits(opcode: Opcode) -> int:
    table = {
        Opcode.ADD: 0x33, Opcode.SUB: 0x33, Opcode.AND: 0x33, Opcode.OR: 0x33,
        Opcode.XOR: 0x33, Opcode.SLL: 0x33, Opcode.SRL: 0x33, Opcode.SRA: 0x33,
        Opcode.SLT: 0x33, Opcode.SLTU: 0x33, Opcode.MUL: 0x33, Opcode.DIV: 0x33,
        Opcode.REM: 0x33,
        Opcode.ADDI: 0x13, Opcode.ANDI: 0x13, Opcode.ORI: 0x13, Opcode.XORI: 0x13,
        Opcode.SLLI: 0x13, Opcode.SRLI: 0x13, Opcode.SRAI: 0x13, Opcode.SLTI: 0x13,
        Opcode.SLTIU: 0x13,
        Opcode.LW: 0x03, Opcode.LH: 0x03, Opcode.LB: 0x03,
        Opcode.SW: 0x23, Opcode.SH: 0x23, Opcode.SB: 0x23,
        Opcode.BEQ: 0x63, Opcode.BNE: 0x63, Opcode.BLT: 0x63, Opcode.BGE: 0x63,
        Opcode.BLTU: 0x63, Opcode.BGEU: 0x63,
        Opcode.LUI: 0x37, Opcode.AUIPC: 0x17,
        Opcode.JAL: 0x6F, Opcode.JALR: 0x67,
        Opcode.CSRRW: 0x73, Opcode.CSRRS: 0x73,
        Opcode.CUSTOM_0: 0x7B, Opcode.CUSTOM_1: 0x7B, Opcode.CUSTOM_2: 0x7B,
    }
    return table.get(opcode, 0x00)


@dataclass
class ISA:
    name: str
    description: str
    instructions: list[Opcode] = field(default_factory=list)
    register_count: int = 32
    xlen: int = 32
    register_convention: RegisterConvention = field(default_factory=RegisterConvention)
    custom_extensions: dict[str, list[Opcode]] = field(default_factory=dict)

    def has_instruction(self, opcode: Opcode) -> bool:
        if opcode in self.instructions:
            return True
        for ext_instrs in self.custom_extensions.values():
            if opcode in ext_instrs:
                return True
        return False

    def extension_names(self) -> list[str]:
        return list(self.custom_extensions.keys())


RISCV_ISA = ISA(
    name="RISC-V RV32I",
    description="Base RISC-V integer ISA, 32-bit, 2 registers",
    instructions=[
        Opcode.ADD, Opcode.SUB, Opcode.AND, Opcode.OR, Opcode.XOR,
        Opcode.SLL, Opcode.SRL, Opcode.SRA, Opcode.SLT, Opcode.SLTU,
        Opcode.ADDI, Opcode.ANDI, Opcode.ORI, Opcode.XORI,
        Opcode.SLLI, Opcode.SRLI, Opcode.SRAI, Opcode.SLTI, Opcode.SLTIU,
        Opcode.LW, Opcode.LH, Opcode.LB,
        Opcode.SW, Opcode.SH, Opcode.SB,
        Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGE, Opcode.BLTU, Opcode.BGEU,
        Opcode.LUI, Opcode.AUIPC,
        Opcode.JAL, Opcode.JALR,
    ],
    register_count=32,
    xlen=32,
)

RISCV_ISA.custom_extensions["M"] = [Opcode.MUL, Opcode.DIV, Opcode.REM]

CUSTOM_ISA = ISA(
    name="Orchestra-A1",
    description="Custom experimenta ISA — RISC-V-inspired with custom opcode space",
    instructions=[
        Opcode.ADD, Opcode.SUB, Opcode.AND, Opcode.OR, Opcode.XOR,
        Opcode.ADDI, Opcode.LW, Opcode.SW,
        Opcode.BEQ, Opcode.BNE, Opcode.JAL, Opcode.JALR,
        Opcode.LUI,
        Opcode.CUSTOM_0, Opcode.CUSTOM_1, Opcode.CUSTOM_2,
    ],
    register_count=16,
    xlen=32,
    custom_extensions={
        "C0": [Opcode.CUSTOM_0],
        "C1": [Opcode.CUSTOM_1, Opcode.CUSTOM_2],
    },
)
