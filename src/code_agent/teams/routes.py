from fastapi import APIRouter, HTTPException

from code_agent.agentmesh import AgentNode, AgentInfo, AgentType, AgentStatus
from code_agent.agentmesh.routes import get_mesh
from code_agent.teams import TeamFactory, AgentTeam, TeamLeader, SwarmCoordinator


_teams_store: dict[str, AgentTeam] = {}
_factory: TeamFactory | None = None
_coordinator: SwarmCoordinator | None = None


def get_factory() -> TeamFactory:
    global _factory
    if _factory is None:
        _factory = TeamFactory(get_mesh().registry)
    return _factory


def get_coordinator() -> SwarmCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = SwarmCoordinator(get_mesh())
    return _coordinator


def register_teams_routes(app, prefix: str = "/api/teams"):
    router = APIRouter(prefix=prefix)
    mesh = get_mesh()
    factory = get_factory()
    coordinator = get_coordinator()

    @router.post("/form")
    async def form_team(body: dict):
        task = body.get("task", "")
        capabilities = body.get("capabilities")
        strategy = body.get("strategy", "best_fit")
        team_name = body.get("name", "")

        result = await factory.form_team(task, capabilities, strategy, team_name)
        if not result.members:
            raise HTTPException(404, "No available agents found for the required capabilities")

        leader_node = None
        for agent_info in result.members:
            existing = mesh.get_node(agent_info.id)
            if existing:
                node = existing
            else:
                node = AgentNode(agent_info)
                await node.start(mesh.registry)
                mesh.register_node(node)
            if leader_node is None:
                leader_node = node

        if not leader_node:
            raise HTTPException(500, "Failed to create team")

        member_nodes = []
        for agent_info in result.members[1:]:
            node = mesh.get_node(agent_info.id)
            if node:
                member_nodes.append(node)

        team = AgentTeam(
            team_id=result.team_id,
            name=result.team_id[:8] if not team_name else team_name,
            leader=leader_node,
            members=member_nodes,
            mesh=mesh,
        )
        _teams_store[team.id] = team

        return {
            "team_id": team.id,
            "name": team.name,
            "members": [m.id for m in team.all_nodes],
            "leader_id": leader_node.id,
            "missing_capabilities": result.missing_capabilities,
            "strategy_used": result.strategy_used,
            "formation_time_ms": result.formation_time_ms,
        }

    @router.post("/teams/{team_id}/execute")
    async def execute_team(team_id: str, body: dict):
        task = body.get("task", "")
        team = _teams_store.get(team_id)
        if not team:
            raise HTTPException(404, "Team not found")
        result = await team.execute(task)
        return {
            "team_id": team.id,
            "status": result.status.value,
            "output": result.output,
            "member_outputs": result.member_outputs,
            "execution_time_ms": result.execution_time_ms,
        }

    @router.get("/teams")
    async def list_teams():
        return {
            "teams": [
                {
                    "id": t.id,
                    "name": t.name,
                    "status": t.status.value,
                    "member_count": len(t.members) + 1,
                    "leader_id": t.leader.id,
                }
                for t in _teams_store.values()
            ],
            "count": len(_teams_store),
        }

    @router.get("/teams/{team_id}")
    async def get_team(team_id: str):
        team = _teams_store.get(team_id)
        if not team:
            raise HTTPException(404, "Team not found")
        return {
            "id": team.id,
            "name": team.name,
            "status": team.status.value,
            "leader_id": team.leader.id,
            "members": list(team.members.keys()),
            "created_at": team.created_at,
            "completed_at": team.completed_at,
        }

    @router.delete("/teams/{team_id}")
    async def disband_team(team_id: str):
        team = _teams_store.pop(team_id, None)
        if not team:
            raise HTTPException(404, "Team not found")
        return {"status": "disbanded"}

    @router.post("/swarm/consensus")
    async def swarm_consensus(body: dict):
        question = body.get("question", "")
        agent_ids = body.get("agent_ids", [])
        rounds = body.get("rounds", 3)

        agents = [mesh.get_node(aid) for aid in agent_ids]
        agents = [a for a in agents if a is not None]
        if len(agents) < 2:
            raise HTTPException(400, "Need at least 2 agents for consensus")

        result = await coordinator.consensus(question, agents, rounds)
        return {
            "output": result.output,
            "agent_outputs": result.agent_outputs,
            "execution_time_ms": result.execution_time_ms,
            "rounds": result.rounds,
        }

    @router.post("/swarm/hierarchical")
    async def swarm_hierarchical(body: dict):
        task = body.get("task", "")
        leader_id = body.get("leader_id", "")
        groups = body.get("groups", {})

        leader = mesh.get_node(leader_id)
        if not leader:
            raise HTTPException(404, "Leader agent not found")

        subtask_map = {}
        for subtask_name, agent_ids in groups.items():
            agents = [mesh.get_node(aid) for aid in agent_ids]
            agents = [a for a in agents if a is not None]
            if agents:
                subtask_map[subtask_name] = agents

        result = await coordinator.hierarchical(task, leader, subtask_map)
        return {
            "output": result.output,
            "agent_outputs": result.agent_outputs,
            "execution_time_ms": result.execution_time_ms,
        }

    @router.post("/swarm/collaborative")
    async def swarm_collaborative(body: dict):
        task = body.get("task", "")
        agent_ids = body.get("agent_ids", [])
        breakdown = body.get("breakdown")

        agents = [mesh.get_node(aid) for aid in agent_ids]
        agents = [a for a in agents if a is not None]
        if not agents:
            raise HTTPException(400, "No available agents found")

        result = await coordinator.collaborative(task, agents, breakdown)
        return {
            "output": result.output,
            "agent_outputs": result.agent_outputs,
            "execution_time_ms": result.execution_time_ms,
        }

    @router.post("/swarm/competitive")
    async def swarm_competitive(body: dict):
        task = body.get("task", "")
        agent_ids = body.get("agent_ids", [])

        agents = [mesh.get_node(aid) for aid in agent_ids]
        agents = [a for a in agents if a is not None]
        if len(agents) < 2:
            raise HTTPException(400, "Need at least 2 agents for competition")

        result = await coordinator.competitive(task, agents)
        return {
            "output": result.output,
            "agent_outputs": result.agent_outputs,
            "execution_time_ms": result.execution_time_ms,
        }

    @router.get("/analyze-task")
    async def analyze_task(task: str):
        capabilities = factory.analyze_task(task)
        return {"task": task, "required_capabilities": capabilities}

    app.include_router(router)
