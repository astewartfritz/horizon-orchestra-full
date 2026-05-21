import uuid
import time
import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field

from orchestra.code_agent.agentmesh import AgentNode, AgentInfo, AgentRegistry, MeshMessage, MessageType, MeshNetwork
from orchestra.code_agent.teams.formation import TeamFactory

logger = logging.getLogger(__name__)


class TeamStatus(str, Enum):
    FORMING = "forming"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TeamResult:
    team_id: str = ""
    status: TeamStatus = TeamStatus.COMPLETED
    output: str = ""
    member_outputs: dict[str, str] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    error: str = ""


class AgentTeam:
    def __init__(self, team_id: str, name: str, leader: AgentNode,
                 members: list[AgentNode], mesh: MeshNetwork):
        self.id = team_id
        self.name = name
        self.leader = leader
        self.members = {m.id: m for m in members}
        self.mesh = mesh
        self.status = TeamStatus.FORMING
        self.created_at = time.time()
        self.completed_at: float | None = None
        self._result: TeamResult | None = None

    @property
    def all_nodes(self) -> list[AgentNode]:
        return [self.leader] + list(self.members.values())

    async def execute(self, task: str) -> TeamResult:
        start = time.time()
        self.status = TeamStatus.PLANNING
        plan = await self.leader.handle_message(MeshMessage(
            sender_id=self.leader.id,
            message_type=MessageType.REQUEST,
            content=f"Plan this task and break it into subtasks for your team members: {task}",
        ))
        plan_text = plan.content if plan else task
        self.status = TeamStatus.EXECUTING

        if not self.members:
            result = await self.leader.handle_message(MeshMessage(
                sender_id=self.leader.id,
                message_type=MessageType.REQUEST,
                content=task,
            ))
            output = result.content if result else ""
            member_outputs = {self.leader.id: output}
        else:
            subtask = task
            member_outputs: dict[str, str] = {}

            for member_id, member in self.members.items():
                result = await member.handle_message(MeshMessage(
                    sender_id=self.leader.id,
                    target_id=member_id,
                    message_type=MessageType.DELEGATE,
                    content=f"{subtask}\n\nContext/Plan: {plan_text}",
                ))
                member_outputs[member_id] = result.content if result else ""

            leader_summary = await self.leader.handle_message(MeshMessage(
                sender_id=self.leader.id,
                message_type=MessageType.REQUEST,
                content=f"Synthesize results from your team:\n" + "\n".join(
                    f"--- {mid} ---\n{out}" for mid, out in member_outputs.items()
                ),
            ))
            output = leader_summary.content if leader_summary else ""

        self.status = TeamStatus.REVIEWING
        self.status = TeamStatus.COMPLETED
        self.completed_at = time.time()

        self._result = TeamResult(
            team_id=self.id,
            status=self.status,
            output=output,
            member_outputs=member_outputs,
            execution_time_ms=(time.time() - start) * 1000,
        )
        return self._result

    async def add_member(self, node: AgentNode):
        if node.id not in self.members and node.id != self.leader.id:
            self.members[node.id] = node
            self.mesh.register_node(node)

    async def remove_member(self, agent_id: str):
        self.members.pop(agent_id, None)


class TeamLeader:
    def __init__(self, node: AgentNode):
        self.node = node

    async def delegate_task(self, task: str, team: AgentTeam) -> TeamResult:
        return await team.execute(task)

    async def synthesize_results(self, results: dict[str, str]) -> str:
        msg = MeshMessage(
            sender_id=self.node.id,
            message_type=MessageType.REQUEST,
            content="Synthesize these team results:\n" + "\n".join(
                f"{k}: {v}" for k, v in results.items()
            ),
        )
        response = await self.node.handle_message(msg)
        return response.content if response else ""
