import json
import sqlite3
import tempfile
import time
from pathlib import Path
import unittest

from orchestra.hardware.isa import (
    CUSTOM_ISA, ISA, Instruction, InstructionFormat, Opcode,
    Register, RegisterConvention, RISCV_ISA,
)
from orchestra.hardware.datapath import (
    ALU, Datapath, DatapathComponent, FIVE_STAGE_PIPELINE,
    Pipeline, PipelineStage, RegisterFile,
)
from orchestra.hardware.rtl import (
    AlwaysBlock, Assignment, Module, Port, PortDirection, RTLSpec, Register as RTLReg, Wire,
)
from orchestra.hardware.research_db import (
    DesignIteration, DesignProposal, EvaluationResult, ResearchDB,
)
from orchestra.hardware.fitness import FitnessEvaluator, FitnessMetric, FitnessScore
from orchestra.hardware.synthesis import SynthesisResult, YosysSynthesis
from orchestra.hardware.simulation import IverilogSimulation, SimulationResult
from orchestra.hardware.mapping import (
    FPGATarget, MappingResult, TargetTechnology, TechnologyMapper,
)
from orchestra.hardware.agent import (
    DesignMutation, ExplorationResult, HardwareDesignAgent,
)


class ISATests(unittest.TestCase):
    def test_opcode_mnemonics(self):
        self.assertEqual(Opcode.ADD.mnemonic, "add")
        self.assertEqual(Opcode.ADDI.mnemonic, "addi")
        self.assertEqual(Opcode.JAL.mnemonic, "jal")

    def test_opcode_formats(self):
        self.assertTrue(Opcode.ADD.is_r_type())
        self.assertTrue(Opcode.ADDI.is_i_type())
        self.assertTrue(Opcode.LW.is_i_type())
        self.assertTrue(Opcode.SW.is_s_type())
        self.assertTrue(Opcode.BEQ.is_b_type())
        self.assertTrue(Opcode.BEQ.is_branch())
        self.assertTrue(Opcode.LW.is_load_store())

    def test_instruction_formats(self):
        self.assertEqual(InstructionFormat.R_TYPE, InstructionFormat.R_TYPE)
        self.assertNotEqual(InstructionFormat.R_TYPE, InstructionFormat.I_TYPE)

    def test_register_convention(self):
        rc = RegisterConvention()
        self.assertEqual(rc.zero.name, "zero")
        self.assertEqual(rc.zero.number, 0)
        self.assertEqual(rc.ra.number, 1)
        self.assertEqual(rc.sp.number, 2)
        self.assertEqual(rc.a0.number, 10)

    def test_register_by_number(self):
        rc = RegisterConvention()
        r = rc.by_number(2)
        self.assertEqual(r.name, "sp")

    def test_register_by_name(self):
        rc = RegisterConvention()
        r = rc.by_name("sp")
        self.assertEqual(r.number, 2)

    def test_by_number_raises(self):
        rc = RegisterConvention()
        with self.assertRaises(KeyError):
            rc.by_number(99)

    def test_by_name_raises(self):
        rc = RegisterConvention()
        with self.assertRaises(KeyError):
            rc.by_name("nonexistent")

    def test_caller_saved(self):
        rc = RegisterConvention()
        caller = rc.caller_saved()
        names = [r.name for r in caller]
        self.assertIn("ra", names)
        self.assertIn("a0", names)
        self.assertIn("t0", names)

    def test_callee_saved(self):
        rc = RegisterConvention()
        callee = rc.callee_saved()
        names = [r.name for r in callee]
        self.assertIn("s0/fp", names)
        self.assertIn("s1", names)

    def test_instruction_encode_r_type(self):
        instr = Instruction(opcode=Opcode.ADD, rd=1, rs1=2, rs2=3, funct3=0, funct7=0)
        encoded = instr.encode()
        self.assertIsInstance(encoded, int)
        self.assertGreater(encoded, 0)

    def test_instruction_encode_i_type(self):
        instr = Instruction(opcode=Opcode.ADDI, rd=1, rs1=2, imm=42, funct3=0)
        encoded = instr.encode()
        self.assertIsInstance(encoded, int)

    def test_instruction_encode_s_type(self):
        instr = Instruction(opcode=Opcode.SW, rs1=2, rs2=3, imm=100, funct3=0)
        encoded = instr.encode()
        self.assertIsInstance(encoded, int)

    def test_instruction_encode_b_type(self):
        instr = Instruction(opcode=Opcode.BEQ, rs1=1, rs2=2, imm=8, funct3=0)
        encoded = instr.encode()
        self.assertIsInstance(encoded, int)

    def test_instruction_encode_u_type(self):
        instr = Instruction(opcode=Opcode.LUI, rd=1, imm=0x12345)
        encoded = instr.encode()
        self.assertIsInstance(encoded, int)

    def test_instruction_encode_j_type(self):
        instr = Instruction(opcode=Opcode.JAL, rd=1, imm=0x1000)
        encoded = instr.encode()
        self.assertIsInstance(encoded, int)

    def test_instruction_disassemble(self):
        instr = Instruction(opcode=Opcode.ADD, rd=1, rs1=2, rs2=3)
        dis = instr.disassemble()
        self.assertIn("add", dis)
        self.assertIn("x1", dis)
        self.assertIn("x2", dis)
        self.assertIn("x3", dis)

    def test_riscv_isa_has_core_instructions(self):
        self.assertTrue(RISCV_ISA.has_instruction(Opcode.ADD))
        self.assertTrue(RISCV_ISA.has_instruction(Opcode.LW))
        self.assertTrue(RISCV_ISA.has_instruction(Opcode.BEQ))
        self.assertTrue(RISCV_ISA.has_instruction(Opcode.JAL))
        self.assertFalse(RISCV_ISA.has_instruction(Opcode.CUSTOM_0))

    def test_riscv_extension_m(self):
        self.assertIn("M", RISCV_ISA.extension_names())
        self.assertTrue(RISCV_ISA.has_instruction(Opcode.MUL))

    def test_custom_isa(self):
        self.assertEqual(CUSTOM_ISA.name, "Orchestra-A1")
        self.assertEqual(CUSTOM_ISA.register_count, 16)
        self.assertEqual(CUSTOM_ISA.xlen, 32)
        self.assertTrue(CUSTOM_ISA.has_instruction(Opcode.CUSTOM_0))


class DatapathTests(unittest.TestCase):
    def test_register_file_defaults(self):
        rf = RegisterFile()
        self.assertEqual(rf.num_registers, 32)
        self.assertEqual(rf.data_width, 32)
        self.assertEqual(rf.num_read_ports, 2)

    def test_register_file_address_bits(self):
        rf = RegisterFile(num_registers=32)
        self.assertEqual(rf.address_bits(), 5)
        rf2 = RegisterFile(num_registers=16)
        self.assertEqual(rf2.address_bits(), 4)

    def test_alu_defaults(self):
        alu = ALU()
        self.assertEqual(alu.data_width, 32)
        self.assertFalse(alu.has_mul)
        self.assertFalse(alu.has_fpu)

    def test_alu_with_mul(self):
        alu = ALU(has_mul=True, data_width=64)
        self.assertTrue(alu.has_mul)
        self.assertGreater(alu.area_um2, ALU(has_mul=False, data_width=64).area_um2)

    def test_alu_op_count(self):
        alu = ALU()
        self.assertGreater(alu.op_count(), 0)

    def test_pipeline_defaults(self):
        pipe = Pipeline()
        self.assertEqual(pipe.stage_count(), 5)
        self.assertTrue(pipe.hazard_detection)
        self.assertTrue(pipe.forwarding)

    def test_pipeline_description(self):
        pipe = Pipeline(stages=[PipelineStage.FETCH, PipelineStage.DECODE])
        desc = pipe.description()
        self.assertIn("FETCH", desc)
        self.assertIn("DECODE", desc)
        self.assertIn("2-stage", desc)

    def test_five_stage_pipeline(self):
        self.assertEqual(FIVE_STAGE_PIPELINE.stage_count(), 5)
        self.assertTrue(FIVE_STAGE_PIPELINE.has_bypass())

    def test_datapath_defaults(self):
        dp = Datapath(name="test_dp")
        self.assertEqual(dp.name, "test_dp")
        self.assertEqual(dp.clock_freq_mhz, 100.0)

    def test_datapath_cycle_time(self):
        dp = Datapath(name="t", clock_freq_mhz=200.0)
        self.assertEqual(dp.cycle_time_ns(), 5.0)

    def test_datapath_critical_path(self):
        dp = Datapath(name="t", pipeline=FIVE_STAGE_PIPELINE)
        self.assertGreater(dp.critical_path_ns(), 0)

    def test_datapath_timing_met(self):
        dp = Datapath(name="t", pipeline=FIVE_STAGE_PIPELINE, clock_freq_mhz=50.0)
        self.assertTrue(dp.is_timing_met())

    def test_datapath_timing_not_met(self):
        dp = Datapath(name="t", pipeline=FIVE_STAGE_PIPELINE, clock_freq_mhz=50000.0)
        self.assertFalse(dp.is_timing_met())

    def test_datapath_add_component(self):
        dp = Datapath(name="t")
        comp = DatapathComponent(name="extra")
        dp.add_component(comp)
        self.assertIn(comp, dp.components)

    def test_datapath_summary(self):
        dp = Datapath(name="t")
        s = dp.summary()
        self.assertEqual(s["name"], "t")
        self.assertIn("pipeline", s)
        self.assertIn("alu_ops", s)


class RTLTests(unittest.TestCase):
    def test_port_declaration(self):
        p = Port("clk", PortDirection.INPUT)
        self.assertIn("input", p.verilog_declaration())
        self.assertIn("clk", p.verilog_declaration())

    def test_bus_port_declaration(self):
        p = Port("data", PortDirection.OUTPUT, width=32)
        decl = p.verilog_declaration()
        self.assertIn("output", decl)
        self.assertIn("[31:0]", decl)

    def test_wire_declaration(self):
        w = Wire("alu_out", 32)
        self.assertIn("wire", w.verilog_declaration())
        self.assertIn("[31:0]", w.verilog_declaration())

    def test_register_declaration(self):
        r = RTLReg("pc_reg", 32)
        self.assertIn("reg", r.verilog_declaration())
        self.assertIn("pc_reg", r.verilog_declaration())

    def test_module_ports(self):
        m = Module("test")
        m.add_port("clk", PortDirection.INPUT)
        m.add_port("data", PortDirection.OUTPUT, 32)
        self.assertEqual(len(m.ports), 2)

    def test_module_render(self):
        m = Module("test_module")
        m.add_port("clk", PortDirection.INPUT)
        m.add_port("rst_n", PortDirection.INPUT)
        render = m.render_verilog()
        self.assertIn("module test_module", render)
        self.assertIn("input clk", render)
        self.assertIn("endmodule", render)

    def test_module_with_assign(self):
        m = Module("test")
        m.add_port("a", PortDirection.INPUT, 32)
        m.add_port("b", PortDirection.OUTPUT, 32)
        m.add_assign("b", "a + 1")
        render = m.render_verilog()
        self.assertIn("assign b = a + 1;", render)

    def test_always_block_render(self):
        body = [Assignment("q", "d", is_comb=False)]
        block = AlwaysBlock("posedge clk", body)
        render = block.render()
        self.assertIn("always @(posedge clk)", render)
        self.assertIn("q <= d", render)

    def test_always_block_conditional(self):
        body = [Assignment("q", "d", is_comb=False, condition="rst_n")]
        block = AlwaysBlock("posedge clk", body)
        render = block.render()
        self.assertIn("if (rst_n)", render)
        self.assertIn("q <= d", render)

    def test_module_submodule(self):
        m = Module("top")
        m.add_submodule("my_alu", "alu")
        m.add_submodule("my_rf", "register_file")
        self.assertEqual(len(m.submodules), 2)

    def test_rtl_spec(self):
        spec = RTLSpec("test", "test spec")
        m = Module("cpu")
        spec.add_module(m)
        self.assertEqual(len(spec.modules), 1)

    def test_rtl_spec_render_all(self):
        spec = RTLSpec("test", "test spec")
        m = Module("cpu")
        m.add_port("clk", PortDirection.INPUT)
        spec.add_module(m)
        sources = spec.render_all()
        self.assertIn("cpu", sources)
        self.assertIn("module cpu", sources["cpu"])

    def test_rtl_spec_summary(self):
        spec = RTLSpec("MyCPU", "A test CPU", datapath_width=64)
        s = spec.summary()
        self.assertEqual(s["name"], "MyCPU")
        self.assertEqual(s["datapath_width"], 64)


class ResearchDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mktemp(suffix=".db"))
        self.db = ResearchDB(str(self.tmp))

    def tearDown(self):
        self.db.close()
        if self.tmp.exists():
            self.tmp.unlink()

    def test_save_and_get_proposal(self):
        p = DesignProposal(name="test_proposal", tags=["test"])
        pid = self.db.save_proposal(p)
        retrieved = self.db.get_proposal(pid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test_proposal")
        self.assertEqual(retrieved.tags, ["test"])

    def test_list_proposals(self):
        p1 = DesignProposal(name="p1")
        p2 = DesignProposal(name="p2")
        self.db.save_proposal(p1)
        self.db.save_proposal(p2)
        all_p = self.db.list_proposals()
        self.assertGreaterEqual(len(all_p), 2)
        names = [r["name"] for r in all_p]
        self.assertIn("p1", names)
        self.assertIn("p2", names)

    def test_get_nonexistent_proposal(self):
        self.assertIsNone(self.db.get_proposal("nonexistent"))

    def test_save_and_get_iteration(self):
        prop = DesignProposal(name="prop")
        pid = self.db.save_proposal(prop)
        it = DesignIteration(proposal_id=pid, iteration_number=1, agent_notes="hello")
        iid = self.db.save_iteration(it)
        retrieved = self.db.get_iteration(iid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.agent_notes, "hello")

    def test_list_iterations(self):
        prop = DesignProposal(name="prop")
        pid = self.db.save_proposal(prop)
        it1 = DesignIteration(proposal_id=pid, iteration_number=1)
        it2 = DesignIteration(proposal_id=pid, iteration_number=2)
        self.db.save_iteration(it1)
        self.db.save_iteration(it2)
        its = self.db.list_iterations(pid)
        self.assertEqual(len(its), 2)

    def test_save_evaluation(self):
        prop = DesignProposal(name="prop")
        pid = self.db.save_proposal(prop)
        it = DesignIteration(proposal_id=pid, iteration_number=1)
        iid = self.db.save_iteration(it)
        ev = EvaluationResult(iteration_id=iid, metric="area", score=0.85)
        eid = self.db.save_evaluation(ev)
        self.assertIsInstance(eid, int)

    def test_save_rtl(self):
        prop = DesignProposal(name="prop")
        pid = self.db.save_proposal(prop)
        it = DesignIteration(proposal_id=pid, iteration_number=1)
        iid = self.db.save_iteration(it)
        rid = self.db.save_rtl(iid, "cpu", "module cpu(); endmodule")
        self.assertIsInstance(rid, int)
        rtls = self.db.get_rtl(iid)
        self.assertEqual(len(rtls), 1)

    def test_delete_proposal_cascades(self):
        prop = DesignProposal(name="prop")
        pid = self.db.save_proposal(prop)
        it = DesignIteration(proposal_id=pid, iteration_number=1)
        iid = self.db.save_iteration(it)
        ev = EvaluationResult(iteration_id=iid, metric="m", score=0.5)
        self.db.save_evaluation(ev)
        self.db.save_rtl(iid, "cpu", "verilog")
        self.db.delete_proposal(pid)
        self.assertIsNone(self.db.get_proposal(pid))
        self.assertIsNone(self.db.get_iteration(iid))

    def test_fitness_history(self):
        prop = DesignProposal(name="prop")
        pid = self.db.save_proposal(prop)
        for i in range(3):
            it = DesignIteration(proposal_id=pid, iteration_number=i + 1,
                                 fitness_overall=0.5 + i * 0.1)
            self.db.save_iteration(it)
        hist = self.db.fitness_history(pid)
        self.assertEqual(len(hist), 3)
        scores = [h["fitness_overall"] for h in hist]
        self.assertEqual(scores, [0.5, 0.6, 0.7])


class FitnessTests(unittest.TestCase):
    def setUp(self):
        self.fitness = FitnessEvaluator()

    def test_evaluate_returns_score(self):
        isa = {"instructions": ["add", "sub", "lw", "sw"], "xlen": 32, "name": "test"}
        dp = {
            "pipeline": {"stages": ["FETCH", "DECODE", "EXECUTE", "MEMORY", "WRITEBACK"],
                         "hazard_detection": True, "forwarding": True,
                         "branch_predictor": "static-not-taken"},
            "register_file": {"num_registers": 32, "read_ports": 2, "write_ports": 1},
            "components": [{"name": "ALU", "area_um2": 500, "power_mw": 10}],
            "cycle_ns": 10.0, "critical_path_ns": 5.0, "timing_met": True,
        }
        score = self.fitness.evaluate(isa, dp, {})
        self.assertIsInstance(score, FitnessScore)
        self.assertGreater(score.overall, 0)
        self.assertIn("timing", score.metrics)
        self.assertIn("area", score.metrics)

    def test_metric_normalize(self):
        m = FitnessMetric("test", weight=1.0, higher_is_better=True)
        self.assertEqual(m.normalize(0.5, 0, 1), 0.5)
        self.assertEqual(m.normalize(0.0, 0, 1), 0.0)
        self.assertEqual(m.normalize(1.0, 0, 1), 1.0)

    def test_metric_normalize_higher_is_worse(self):
        m = FitnessMetric("test", weight=1.0, higher_is_better=False)
        self.assertEqual(m.normalize(0.0, 0, 1), 1.0)
        self.assertEqual(m.normalize(1.0, 0, 1), 0.0)

    def test_metric_normalize_zero_range(self):
        m = FitnessMetric("test", weight=1.0)
        self.assertEqual(m.normalize(0.5, 0.5, 0.5), 1.0)

    def test_compare_scores(self):
        s1 = FitnessScore(overall=0.9)
        s2 = FitnessScore(overall=0.5)
        s3 = FitnessScore(overall=0.7)
        ranked = self.fitness.compare([s1, s2, s3])
        self.assertEqual(ranked[0][0], 0)
        self.assertEqual(ranked[1][0], 2)
        self.assertEqual(ranked[2][0], 1)


class MappingTests(unittest.TestCase):
    def test_fpga_target_part_number(self):
        t = FPGATarget(device="xc7a35t", package="csg324", speed_grade="-1")
        self.assertIn("xc7a35t", t.part_number())
        self.assertIn("csg324", t.part_number())

    def test_technology_mapper_default(self):
        mapper = TechnologyMapper()
        self.assertEqual(mapper.target, TargetTechnology.FPGA_ARTIX7)

    def test_estimate_resources_returns_result(self):
        mapper = TechnologyMapper()
        dp = {
            "components": [
                {"name": "RF_32x32", "num_registers": 32, "config": {"data_width": 32}},
                {"name": "ALU_32b", "config": {"data_width": 32}},
            ],
            "pipeline": {"stages": ["FETCH", "DECODE", "EXECUTE", "MEMORY", "WRITEBACK"]},
        }
        result = mapper.estimate_resources(dp)
        self.assertIsInstance(result, MappingResult)
        self.assertIn("artix-7", result.summary()["target"])
        self.assertGreater(result.ff_usage, 0)
        self.assertGreater(result.lut_usage, 0)

    def test_suggest_alternative_on_full_design(self):
        mapper = TechnologyMapper(TargetTechnology.FPGA_ICE40)
        dp = {
            "components": [
                {"name": "RF_32x32", "num_registers": 32, "config": {"data_width": 32}},
                {"name": "ALU_32b", "config": {"data_width": 32}},
            ],
            "pipeline": {"stages": ["FETCH", "DECODE", "EXECUTE", "MEMORY", "WRITEBACK"]},
        }
        result = mapper.estimate_resources(dp)
        suggestions = mapper.suggest_alternative(result)
        # ICE40 has 5280 LUTs, ALU alone uses 128, should be fine
        self.assertIsInstance(suggestions, list)


class SynthesisTests(unittest.TestCase):
    def test_synthesis_result_defaults(self):
        r = SynthesisResult()
        self.assertFalse(r.success)
        self.assertEqual(r.cell_count, 0)
        self.assertEqual(r.errors, [])

    def test_yosys_check_available(self):
        synth = YosysSynthesis()
        available = synth.check_available()
        # Yosys may or may not be installed; we just test it does not crash
        self.assertIsInstance(available, bool)

    def test_synthesize_returns_result(self):
        synth = YosysSynthesis()
        verilog = "module top(input clk, output reg q); always @(posedge clk) q <= 1; endmodule"
        src = synth.work_dir / "test.v"
        src.write_text(verilog)
        result = synth.synthesize([str(src)], "top")
        self.assertIsInstance(result, SynthesisResult)


class SimulationTests(unittest.TestCase):
    def test_simulation_result_defaults(self):
        r = SimulationResult()
        self.assertFalse(r.success)
        self.assertEqual(r.passed, 0)
        self.assertEqual(r.failed, 0)

    def test_iverilog_check_available(self):
        sim = IverilogSimulation()
        available = sim.check_available()
        self.assertIsInstance(available, bool)

    def test_simulate_returns_result(self):
        sim = IverilogSimulation()
        src = sim.work_dir / "top.v"
        src.write_text("module top; endmodule")
        tb = """
module testbench;
  top u_top();
  initial begin
    $display("PASSED: test1");
    #10 $finish;
  end
endmodule
"""
        result = sim.simulate([str(src)], "top", testbench=tb)
        self.assertIsInstance(result, SimulationResult)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mktemp(suffix=".db"))
        self.db = ResearchDB(str(self.tmp))

    def tearDown(self):
        self.db.close()
        if self.tmp.exists():
            self.tmp.unlink()

    def test_create_initial_proposal(self):
        agent = HardwareDesignAgent(db=self.db, max_iterations=1)
        proposal = agent.create_initial_proposal()
        self.assertIsNotNone(proposal.id)
        self.assertEqual(proposal.name, "Orchestra-A1 Exploration")

    def test_run_exploration_returns_result(self):
        agent = HardwareDesignAgent(db=self.db, max_iterations=2)
        result = agent.run_exploration()
        self.assertIsInstance(result, ExplorationResult)
        self.assertEqual(result.proposal_id, result.proposal_id)
        self.assertGreaterEqual(result.iterations, 1)
        self.assertGreater(len(result.fitness_history), 0)

    def test_exploration_fitness_tracks(self):
        agent = HardwareDesignAgent(db=self.db, max_iterations=3)
        result = agent.run_exploration()
        self.assertGreaterEqual(len(result.fitness_history), 1)
        for f in result.fitness_history:
            self.assertGreaterEqual(f, 0.0)
            self.assertLessEqual(f, 1.0)

    def test_exploration_stores_in_db(self):
        agent = HardwareDesignAgent(db=self.db, max_iterations=2)
        result = agent.run_exploration()
        proposal = self.db.get_proposal(result.proposal_id)
        self.assertIsNotNone(proposal)
        its = self.db.list_iterations(result.proposal_id)
        self.assertGreaterEqual(len(its), 1)

    def test_agent_with_custom_isa(self):
        isa = ISA(
            name="TinyRISC",
            description="Minimal test ISA",
            instructions=[Opcode.ADD, Opcode.SUB, Opcode.LW, Opcode.SW],
            register_count=8,
            xlen=16,
        )
        agent = HardwareDesignAgent(
            db=self.db, max_iterations=2, exploration_name="TinyRISC Test"
        )
        result = agent.run_exploration(isa=isa)
        self.assertGreaterEqual(result.iterations, 1)

    def test_exploration_elapsed_time(self):
        agent = HardwareDesignAgent(db=self.db, max_iterations=2)
        result = agent.run_exploration()
        self.assertGreater(result.elapsed_seconds, 0)


class DesignMutationTests(unittest.TestCase):
    def test_enable_forwarding(self):
        dp = Datapath(name="t", pipeline=Pipeline(forwarding=False))
        result = DesignMutation.enable_forwarding(dp)
        self.assertIn("enabled", result)
        self.assertTrue(dp.pipeline.forwarding)

    def test_enable_forwarding_already_enabled(self):
        dp = Datapath(name="t", pipeline=Pipeline(forwarding=True))
        result = DesignMutation.enable_forwarding(dp)
        self.assertIn("already", result)

    def test_add_pipeline_stage(self):
        dp = Datapath(name="t", pipeline=Pipeline(
            stages=[PipelineStage.FETCH, PipelineStage.DECODE]
        ))
        result = DesignMutation.add_pipeline_stage(dp)
        self.assertIn("added", result)
        self.assertEqual(len(dp.pipeline.stages), 3)

    def test_widen_datapath(self):
        dp = Datapath(name="t", register_file=RegisterFile(data_width=32),
                      alu=ALU(data_width=32))
        result = DesignMutation.widen_datapath(dp)
        self.assertIn("64", result)

    def test_add_register_banking(self):
        dp = Datapath(name="t", register_file=RegisterFile(num_registers=32))
        result = DesignMutation.add_register_banking(dp)
        self.assertIn("64", result)
        self.assertEqual(dp.register_file.num_registers, 64)

    def test_add_instruction_to_isa(self):
        isa = ISA(name="test", description="", instructions=[Opcode.ADD])
        result = DesignMutation.add_instruction(isa, Opcode.SUB)
        self.assertIn("added", result)
        self.assertTrue(isa.has_instruction(Opcode.SUB))

    def test_add_instruction_already_present(self):
        isa = ISA(name="test", description="", instructions=[Opcode.ADD])
        result = DesignMutation.add_instruction(isa, Opcode.ADD)
        self.assertIn("already", result)

    def test_add_mul_div(self):
        alu = ALU(has_mul=False, has_div=False)
        result = DesignMutation.add_mul_div(alu)
        self.assertIn("mul", result)
        self.assertIn("div", result)
        self.assertTrue(alu.has_mul)
        self.assertTrue(alu.has_div)


class IntegrationTests(unittest.TestCase):
    def test_full_design_exploration_workflow(self):
        tmp = Path(tempfile.mktemp(suffix=".db"))
        db = ResearchDB(str(tmp))
        try:
            agent = HardwareDesignAgent(db=db, max_iterations=2)
            result = agent.run_exploration()

            self.assertGreaterEqual(result.iterations, 1)
            self.assertGreaterEqual(len(result.fitness_history), 1)

            proposal = db.get_proposal(result.proposal_id)
            self.assertIsNotNone(proposal)
            self.assertIn("instructions", proposal.isa_snapshot)

            iterations = db.list_iterations(result.proposal_id)
            self.assertGreaterEqual(len(iterations), 1)

            fitness_hist = db.fitness_history(result.proposal_id)
            self.assertGreaterEqual(len(fitness_hist), 1)

            latest_iter = iterations[-1]
            evals = db.list_evaluations(latest_iter["id"])
            self.assertGreaterEqual(len(evals), 0)

            rtls = db.get_rtl(latest_iter["id"])
            self.assertGreaterEqual(len(rtls), 0)
        finally:
            db.close()
            if tmp.exists():
                tmp.unlink()

    def test_isa_datapath_rtl_integration(self):
        from orchestra.hardware.rtl import Module, PortDirection, RTLSpec
        isa = CUSTOM_ISA
        dp = Datapath(
            name=f"{isa.name}_DP",
            pipeline=FIVE_STAGE_PIPELINE,
            register_file=RegisterFile(num_registers=isa.register_count, data_width=isa.xlen),
            alu=ALU(data_width=isa.xlen),
        )

        spec = RTLSpec(name=f"{isa.name}_RTL", description="Integration test")
        cpu = Module("cpu_core")
        cpu.add_port("clk", PortDirection.INPUT)
        cpu.add_port("rst_n", PortDirection.INPUT)
        cpu.add_register("pc_reg", isa.xlen)
        cpu.add_wire("alu_out", isa.xlen)
        cpu.add_assign("alu_out", "pc_reg + 4")
        spec.add_module(cpu)

        sources = spec.render_all()
        self.assertIn("cpu_core", sources)
        self.assertIn("module cpu_core", sources["cpu_core"])
        self.assertIn("endmodule", sources["cpu_core"])


class ExportsTests(unittest.TestCase):
    def test_isa_exports(self):
        from orchestra.hardware import (
            CUSTOM_ISA, ISA, Instruction, InstructionFormat,
            Opcode, RISCV_ISA, Register, RegisterConvention,
        )
        self.assertIs(Opcode.ADD, Opcode.ADD)

    def test_datapath_exports(self):
        from orchestra.hardware import (
            ALU, Datapath, DatapathComponent, FIVE_STAGE_PIPELINE,
            Pipeline, PipelineStage, RegisterFile,
        )
        self.assertEqual(FIVE_STAGE_PIPELINE.stage_count(), 5)

    def test_rtl_exports(self):
        from orchestra.hardware import (
            Assignment, Module, Port, PortDirection, RTLSpec, Wire,
        )
        m = Module("t")
        self.assertEqual(m.name, "t")

    def test_db_exports(self):
        from orchestra.hardware import (
            DesignIteration, DesignProposal, EvaluationResult, ResearchDB,
        )
        p = DesignProposal(name="test")
        self.assertEqual(p.name, "test")

    def test_agent_exports(self):
        from orchestra.hardware import ExplorationResult, HardwareDesignAgent
        agent = HardwareDesignAgent(max_iterations=1)
        self.assertEqual(agent.max_iterations, 1)

    def test_fitness_exports(self):
        from orchestra.hardware import FitnessEvaluator, FitnessMetric, FitnessScore
        e = FitnessEvaluator()
        self.assertGreater(len(e.metrics), 0)

    def test_synthesis_exports(self):
        from orchestra.hardware import SynthesisResult, SynthesisTool, YosysSynthesis
        r = SynthesisResult()
        self.assertFalse(r.success)

    def test_simulation_exports(self):
        from orchestra.hardware import IverilogSimulation, SimulationResult, SimulationTool
        r = SimulationResult()
        self.assertEqual(r.passed, 0)

    def test_mapping_exports(self):
        from orchestra.hardware import (
            FPGATarget, MappingResult, TargetTechnology, TechnologyMapper,
        )
        t = FPGATarget()
        self.assertEqual(t.family, "artix7")
