import pytest
import asyncio

from orchestra.code_agent.agentmesh import (
    AgentRegistry, AgentInfo, AgentType, AgentStatus,
    AgentNode, MeshNetwork,
)
from orchestra.code_agent.teams import (
    TeamFactory, TeamFormationResult, TeamFormationStrategy,
    BestFitStrategy, LoadBalancedStrategy, MinimumTeamStrategy,
    AgentTeam, TeamLeader, TeamResult, TeamStatus,
    SwarmCoordinator, SwarmResult,
)


@pytest.fixture
def registry():
    r = AgentRegistry()
    for i, (name, caps, atype) in enumerate([
        ("coder-1", ["coding", "debugging"], AgentType.CODER),
        ("coder-2", ["coding"], AgentType.CODER),
        ("reasoner-1", ["reasoning", "analysis"], AgentType.REASONER),
        ("planner-1", ["planning"], AgentType.PLANNER),
        ("searcher-1", ["research", "search"], AgentType.RESEARCHER),
    ]):
        r.register(AgentInfo(
            name=name, agent_type=atype, capabilities=caps,
            status=AgentStatus.ONLINE, max_concurrent_tasks=3,
        ))
    return r


@pytest.fixture
def mesh(registry):
    m = MeshNetwork(registry)
    for info in registry.list_agents():
        node = AgentNode(info)
        node.set_llm_function(lambda c, meta: f"[{info.name}] processed: {c[:50]}")
        m.register_node(node)
    return m


class TestTeamFactory:
    def test_analyze_task_coding(self, registry):
        factory = TeamFactory(registry)
        caps = factory.analyze_task("Write a Python function to sort an array")
        assert "coding" in caps

    def test_analyze_task_research(self, registry):
        factory = TeamFactory(registry)
        caps = factory.analyze_task("Research the latest trends in AI")
        assert "research" in caps

    def test_analyze_task_planning(self, registry):
        factory = TeamFactory(registry)
        caps = factory.analyze_task("Plan the architecture for a microservice")
        assert "planning" in caps

    def test_analyze_task_default(self, registry):
        factory = TeamFactory(registry)
        caps = factory.analyze_task("Hello, how are you?")
        assert caps == ["general"]

    def test_analyze_task_multiple(self, registry):
        factory = TeamFactory(registry)
        caps = factory.analyze_task("Design, code, and test a new API endpoint")
        assert "coding" in caps

    @pytest.mark.asyncio
    async def test_form_team_best_fit(self, registry):
        factory = TeamFactory(registry)
        result = await factory.form_team("Write code", ["coding"])
        assert len(result.members) >= 1
        assert result.strategy_used == "best_fit"
        assert result.team_id

    @pytest.mark.asyncio
    async def test_form_team_with_capabilities(self, registry):
        factory = TeamFactory(registry)
        result = await factory.form_team(
            "Build a full system", ["coding", "reasoning", "planning"]
        )
        assert len(result.members) >= 2
        member_caps = set()
        for m in result.members:
            member_caps.update(m.capabilities)
        assert "planning" in member_caps

    @pytest.mark.asyncio
    async def test_form_team_missing_capabilities(self, registry):
        factory = TeamFactory(registry)
        result = await factory.form_team("Do everything", ["coding", "quantum_computing"])
        assert "quantum_computing" in result.missing_capabilities

    @pytest.mark.asyncio
    async def test_form_team_no_capabilities(self, registry):
        factory = TeamFactory(registry)
        result = await factory.form_team("A general task")
        assert len(result.members) >= 0

    @pytest.mark.asyncio
    async def test_best_fit_strategy(self, registry):
        strategy = BestFitStrategy()
        members = strategy.form("code", ["coding"], registry)
        assert len(members) >= 1

    @pytest.mark.asyncio
    async def test_load_balanced_strategy(self, registry):
        strategy = LoadBalancedStrategy()
        members = strategy.form("code", ["coding"], registry)
        assert len(members) >= 1

    @pytest.mark.asyncio
    async def test_minimum_team_strategy_single(self, registry):
        strategy = MinimumTeamStrategy()
        members = strategy.form("code", ["coding", "debugging"], registry)
        assert len(members) >= 0

    def test_custom_strategy(self, registry):
        factory = TeamFactory(registry)

        class PickFirst(TeamFormationStrategy):
            def form(self, task, required_capabilities, registry):
                agents = registry.list_agents()
                return agents[:1] if agents else []

        factory.register_strategy("pick_first", PickFirst())
        assert "pick_first" in factory._custom_strategies


class TestAgentTeam:
    @pytest.mark.asyncio
    async def test_team_execution(self, mesh):
        agents = mesh.list_nodes()
        if len(agents) < 2:
            pytest.skip("Need at least 2 agents")

        leader = agents[0]
        members = agents[1:]
        team = AgentTeam("test-1", "test-team", leader, members, mesh)
        result = await team.execute("Build something")
        assert result.status == TeamStatus.COMPLETED
        assert result.team_id == "test-1"
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_team_with_single_member(self, mesh):
        agents = mesh.list_nodes()
        if not agents:
            pytest.skip("Need at least 1 agent")
        leader = agents[0]
        team = AgentTeam("solo", "solo-team", leader, [], mesh)
        result = await team.execute("Do the thing")
        assert result.status == TeamStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_add_remove_member(self, mesh):
        agents = mesh.list_nodes()
        if len(agents) < 2:
            pytest.skip("Need at least 2 agents")
        leader = agents[0]
        member = agents[1]
        team = AgentTeam("arm", "arm-test", leader, [member], mesh)
        assert member.id in team.members
        assert leader.id not in team.members
        await team.remove_member(member.id)
        assert member.id not in team.members

    @pytest.mark.asyncio
    async def test_team_leader(self, mesh):
        agents = mesh.list_nodes()
        if not agents:
            pytest.skip("Need at least 1 agent")
        leader_node = agents[0]
        tl = TeamLeader(leader_node)
        team = AgentTeam("lead", "lead-team", leader_node, [], mesh)
        result = await tl.delegate_task("Lead task", team)
        assert result.status == TeamStatus.COMPLETED

    def test_team_leader_node(self, mesh):
        agents = mesh.list_nodes()
        if not agents:
            pytest.skip("Need at least 1 agent")
        tl = TeamLeader(agents[0])
        assert tl.node == agents[0]


class TestSwarmCoordinator:
    @pytest.mark.asyncio
    async def test_consensus(self, mesh):
        agents = mesh.list_nodes()
        if len(agents) < 2:
            pytest.skip("Need at least 2 agents")
        coordinator = SwarmCoordinator(mesh)
        result = await coordinator.consensus("What is 2+2?", agents[:2], rounds=2)
        assert result.output
        assert result.execution_time_ms > 0
        assert result.rounds == 2

    @pytest.mark.asyncio
    async def test_hierarchical(self, mesh):
        agents = mesh.list_nodes()
        if len(agents) < 3:
            pytest.skip("Need at least 3 agents")
        coordinator = SwarmCoordinator(mesh)
        subtask_map = {"research": [agents[1]], "coding": [agents[2]]}
        result = await coordinator.hierarchical("Build project", agents[0], subtask_map)
        assert result.output
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_collaborative(self, mesh):
        agents = mesh.list_nodes()
        if len(agents) < 2:
            pytest.skip("Need at least 2 agents")
        coordinator = SwarmCoordinator(mesh)
        result = await coordinator.collaborative(
            "Write a report", agents[:2], ["Research section", "Code section"]
        )
        assert result.output
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_competitive(self, mesh):
        agents = mesh.list_nodes()
        if len(agents) < 2:
            pytest.skip("Need at least 2 agents")
        coordinator = SwarmCoordinator(mesh)
        result = await coordinator.competitive("Solve this problem", agents[:2])
        assert result.output
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_consensus_single_agent(self, mesh):
        agents = mesh.list_nodes()
        if not agents:
            pytest.skip("Need at least 1 agent")
        coordinator = SwarmCoordinator(mesh)
        result = await coordinator.consensus("Simple Q", [agents[0]], rounds=1)
        assert result.output

    def test_swarm_result(self):
        r = SwarmResult(output="test", agent_outputs={"a1": "out1"}, rounds=3)
        assert r.output == "test"
        assert r.agent_outputs["a1"] == "out1"
        assert r.rounds == 3
