from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.hardware.datapath import (
    ALU,
    Datapath,
    FIVE_STAGE_PIPELINE,
    Pipeline,
    PipelineStage,
    RegisterFile,
)
from orchestra.hardware.fitness import FitnessEvaluator, FitnessScore
from orchestra.hardware.isa import CUSTOM_ISA, ISA, Opcode, RISCV_ISA
from orchestra.hardware.mapping import MappingResult, TargetTechnology, TechnologyMapper
from orchestra.hardware.research_db import (
    DesignIteration,
    DesignProposal,
    EvaluationResult,
    ResearchDB,
)
from orchestra.hardware.rtl import Module, PortDirection, RTLSpec


class DesignMutation:
    """Strategies for mutating a hardware design between iterations."""

    @staticmethod
    def add_pipeline_stage(datapath: Datapath) -> str:
        current = datapath.pipeline.stages.copy()
        if len(current) >= 7:
            return "pipeline already optimal"
        missing = []
        for stage in PipelineStage:
            if stage not in current:
                missing.append(stage)
        if missing:
            datapath.pipeline.stages = current + [missing[0]]
            return f"added {missing[0].name} stage"
        return "no stage to add"

    @staticmethod
    def enable_forwarding(datapath: Datapath) -> str:
        if not datapath.pipeline.forwarding:
            datapath.pipeline.forwarding = True
            return "enabled forwarding"
        return "forwarding already enabled"

    @staticmethod
    def add_instruction(isa: ISA, opcode: Opcode) -> str:
        if opcode not in isa.instructions:
            isa.instructions.append(opcode)
            return f"added {opcode.mnemonic}"
        return f"{opcode.mnemonic} already present"

    @staticmethod
    def widen_datapath(datapath: Datapath) -> str:
        target = 64 if datapath.register_file.data_width == 32 else 128
        datapath.register_file.data_width = target
        datapath.alu.data_width = target
        return f"widened datapath to {target}-bit"

    @staticmethod
    def add_register_banking(datapath: Datapath) -> str:
        if datapath.register_file.num_registers < 64:
            datapath.register_file.num_registers = 64
            return "added register banking (32->64)"
        return "register banking already scaled"

    @staticmethod
    def add_mul_div(alu: ALU) -> str:
        changes = []
        if not alu.has_mul:
            alu.has_mul = True
            alu.supported_ops.extend(["mul", "mulh"])
            changes.append("mul")
        if not alu.has_div:
            alu.has_div = True
            alu.supported_ops.extend(["div", "rem"])
            changes.append("div")
        if changes:
            return f"added {', '.join(changes)} to ALU"
        return "mul/div already present"


DEFAULT_MUTATIONS = [
    DesignMutation.enable_forwarding,
    DesignMutation.widen_datapath,
    DesignMutation.add_register_banking,
]


@dataclass
class ExplorationResult:
    proposal_id: str = ""
    iterations: int = 0
    best_fitness: float = 0.0
    fitness_history: list[float] = field(default_factory=list)
    final_snapshot: dict[str, Any] = field(default_factory=dict)
    rtl_modules: dict[str, str] = field(default_factory=dict)
    mapping_result: MappingResult | None = None
    elapsed_seconds: float = 0.0
    summary: str = ""


class HardwareDesignAgent:
    def __init__(
        self,
        db: ResearchDB | None = None,
        fitness_evaluator: FitnessEvaluator | None = None,
        technology_mapper: TechnologyMapper | None = None,
        max_iterations: int = 10,
        fitness_threshold: float = 0.85,
        exploration_name: str = "Orchestra-A1 Exploration",
    ):
        self.db = db or ResearchDB()
        self.fitness = fitness_evaluator or FitnessEvaluator()
        self.mapper = technology_mapper or TechnologyMapper()
        self.max_iterations = max_iterations
        self.fitness_threshold = fitness_threshold
        self.exploration_name = exploration_name
        self.mutations = DEFAULT_MUTATIONS
        self._current_datapath: Datapath | None = None
        self._current_isa: ISA | None = None

    def create_initial_proposal(self, isa: ISA | None = None,
                                datapath: Datapath | None = None) -> DesignProposal:
        isa = isa or CUSTOM_ISA
        dp = datapath or Datapath(
            name=f"{isa.name}_Datapath",
            pipeline=FIVE_STAGE_PIPELINE,
            register_file=RegisterFile(
                num_registers=isa.register_count,
                data_width=isa.xlen,
            ),
            alu=ALU(data_width=isa.xlen),
            clock_freq_mhz=100.0,
        )
        self._current_datapath = dp
        self._current_isa = isa

        isa_dict = {
            "name": isa.name, "xlen": isa.xlen,
            "register_count": isa.register_count,
            "instructions": [op.mnemonic for op in isa.instructions],
            "extensions": isa.extension_names(),
        }
        dp_dict = dp.summary()

        rtl_spec = self._build_rtl_spec(isa, dp)
        rtl_dict = rtl_spec.summary()

        proposal = DesignProposal(
            name=self.exploration_name,
            isa_snapshot=isa_dict,
            datapath_snapshot=dp_dict,
            rtl_snapshot=rtl_dict,
            tags=["initial", isa.name.lower().replace(" ", "-")],
        )
        self.db.save_proposal(proposal)
        return proposal

    def _build_rtl_spec(self, isa: ISA, dp: Datapath) -> RTLSpec:
        spec = RTLSpec(
            name=f"{isa.name}_RTL",
            description=f"RTL spec for {isa.name} on {dp.name}",
            datapath_width=isa.xlen,
        )

        cpu = Module(name="cpu_core")
        cpu.add_port("clk", PortDirection.INPUT)
        cpu.add_port("rst_n", PortDirection.INPUT)
        cpu.add_port("instruction", PortDirection.INPUT, isa.xlen)
        cpu.add_port("read_data", PortDirection.INPUT, isa.xlen)
        cpu.add_port("pc", PortDirection.OUTPUT, isa.xlen)
        cpu.add_port("write_data", PortDirection.OUTPUT, isa.xlen)
        cpu.add_port("alu_result", PortDirection.OUTPUT, isa.xlen)
        cpu.add_register("pc_reg", isa.xlen)
        cpu.add_register("instruction_reg", isa.xlen)
        cpu.add_wire("alu_out", isa.xlen)
        cpu.add_submodule("rf_inst", "register_file")
        cpu.add_submodule("alu_inst", "alu")
        for stage in dp.pipeline.stages:
            cpu.add_register(f"{stage.name.lower()}_reg", isa.xlen)
        spec.add_module(cpu)

        rf = Module(name="register_file")
        rf.add_port("clk", PortDirection.INPUT)
        rf.add_port("raddr1", PortDirection.INPUT, 5)
        rf.add_port("raddr2", PortDirection.INPUT, 5)
        rf.add_port("waddr", PortDirection.INPUT, 5)
        rf.add_port("wdata", PortDirection.INPUT, isa.xlen)
        rf.add_port("rdata1", PortDirection.OUTPUT, isa.xlen)
        rf.add_port("rdata2", PortDirection.OUTPUT, isa.xlen)
        rf.add_port("we", PortDirection.INPUT)
        for i in range(min(8, isa.register_count)):
            rf.add_register(f"x{i}", isa.xlen)
        spec.add_module(rf)

        alu_module = Module(name="alu")
        alu_module.add_port("a", PortDirection.INPUT, isa.xlen)
        alu_module.add_port("b", PortDirection.INPUT, isa.xlen)
        alu_module.add_port("alu_op", PortDirection.INPUT, 4)
        alu_module.add_port("result", PortDirection.OUTPUT, isa.xlen)
        alu_module.add_port("zero", PortDirection.OUTPUT)
        alu_module.add_register("result_reg", isa.xlen)
        spec.add_module(alu_module)

        return spec

    def run_exploration(self, iterations: int | None = None,
                        isa: ISA | None = None,
                        datapath: Datapath | None = None) -> ExplorationResult:
        max_iter = iterations or self.max_iterations
        proposal = self.create_initial_proposal(isa, datapath)
        dp = self._current_datapath
        isa = self._current_isa
        start_time = time.time()
        result = ExplorationResult(proposal_id=proposal.id)
        best_score = FitnessScore()
        best_snapshot = {}

        for i in range(max_iter):
            snapshot = self._snapshot_state(isa, dp)
            score = self.fitness.evaluate(snapshot["isa"], snapshot["datapath"], {})

            iteration = DesignIteration(
                proposal_id=proposal.id,
                iteration_number=i + 1,
                diff_description=f"Iteration {i + 1}",
                changes={},
                fitness_scores=score.metrics,
                fitness_overall=score.overall,
                agent_notes=self._generate_agent_notes(score, i),
            )

            if score.overall > best_score.overall:
                best_score = score
                best_snapshot = snapshot

            # Run mapping estimate
            map_result = self.mapper.estimate_resources(snapshot["datapath"])
            iteration.synthesis_result = map_result.summary()
            iteration.simulation_result = {
                "passed": 0, "failed": 0, "total": 0, "success": True,
            }

            self.db.save_iteration(iteration)

            # Store RTL (must be after save_iteration due to FK)
            rtl_spec = self._build_rtl_spec(isa, dp)
            module_sources = rtl_spec.render_all()
            for mod_name, verilog in module_sources.items():
                self.db.save_rtl(iteration.id, mod_name, verilog)

            eval_entry = EvaluationResult(
                iteration_id=iteration.id,
                metric="overall_fitness",
                score=score.overall,
                details={"iteration": i + 1, "metrics": score.metrics},
            )
            self.db.save_evaluation(eval_entry)

            result.fitness_history.append(score.overall)

            if score.overall >= self.fitness_threshold:
                result.summary = f"Fitness threshold {self.fitness_threshold} met at iteration {i + 1}"
                break

            if i < max_iter - 1:
                self._mutate(isa, dp, i)

        result.iterations = len(result.fitness_history)
        result.best_fitness = best_score.overall
        result.final_snapshot = best_snapshot
        result.mapping_result = map_result if best_score.overall > 0 else None
        result.elapsed_seconds = round(time.time() - start_time, 3)

        final_proposal = self.db.get_proposal(proposal.id)
        if final_proposal:
            result.final_snapshot = {
                "isa": final_proposal.isa_snapshot,
                "datapath": final_proposal.datapath_snapshot,
            }

        return result

    def _snapshot_state(self, isa: ISA, dp: Datapath) -> dict[str, Any]:
        pipeline_dict = {
            "stages": [s.name for s in dp.pipeline.stages],
            "hazard_detection": dp.pipeline.hazard_detection,
            "forwarding": dp.pipeline.forwarding,
            "branch_predictor": dp.pipeline.branch_predictor,
        }
        dp_summary = dp.summary()
        dp_summary["pipeline"] = pipeline_dict
        return {
            "isa": {
                "name": isa.name, "xlen": isa.xlen,
                "register_count": isa.register_count,
                "instructions": [op.mnemonic for op in isa.instructions],
                "extensions": isa.extension_names(),
            },
            "datapath": dp_summary,
        }

    def _mutate(self, isa: ISA, dp: Datapath, iteration: int) -> None:
        for mutation_fn in self.mutations:
            mutation_fn(dp)

        if iteration % 3 == 0:
            for op in [Opcode.MUL, Opcode.DIV, Opcode.REM]:
                DesignMutation.add_instruction(isa, op)

        if iteration % 5 == 0:
            DesignMutation.add_pipeline_stage(dp)

    def _generate_agent_notes(self, score: FitnessScore, iteration: int) -> str:
        strengths = [k for k, v in score.metrics.items() if v >= 0.7]
        weaknesses = [k for k, v in score.metrics.items() if v < 0.4]
        notes = f"Iteration {iteration + 1}: fitness={score.overall:.4f}"
        if strengths:
            notes += f" | strengths: {', '.join(strengths)}"
        if weaknesses:
            notes += f" | weaknesses: {', '.join(weaknesses)}"
        return notes
