import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Callable

from code_agent.agentmesh import AgentNode, MeshNetwork, MeshMessage, MessageType

logger = logging.getLogger(__name__)


@dataclass
class SwarmResult:
    output: str = ""
    agent_outputs: dict[str, str] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    rounds: int = 0


class SwarmCoordinator:
    def __init__(self, mesh: MeshNetwork):
        self.mesh = mesh

    async def consensus(self, question: str, agents: list[AgentNode],
                        rounds: int = 3, consensus_threshold: float = 0.6) -> SwarmResult:
        start = time.time()
        positions: dict[str, str] = {}
        agent_outputs: dict[str, str] = {}

        for agent in agents:
            result = await agent.handle_message(MeshMessage(
                sender_id="coordinator",
                target_id=agent.id,
                message_type=MessageType.REQUEST,
                content=f"State your position on: {question}",
            ))
            positions[agent.id] = result.content if result else ""
            agent_outputs[f"{agent.id}_round_1"] = positions[agent.id]

        for r in range(1, rounds):
            critique_responses = {}
            for agent in agents:
                others = {a_id: pos for a_id, pos in positions.items() if a_id != agent.id}
                critique = await agent.handle_message(MeshMessage(
                    sender_id="coordinator",
                    target_id=agent.id,
                    message_type=MessageType.REQUEST,
                    content=f"Round {r + 1}. Consider these positions and revise yours.\n"
                            f"Your position: {positions.get(agent.id, '')}\n"
                            f"Others: {others}\n"
                            f"Question: {question}",
                ))
                critique_responses[agent.id] = critique.content if critique else ""
                agent_outputs[f"{agent.id}_round_{r + 1}"] = critique_responses[agent.id]
            positions = critique_responses

        all_texts = list(positions.values())
        synthesizer = agents[0] if agents else None
        if synthesizer and len(agents) > 1:
            synthesis = await synthesizer.handle_message(MeshMessage(
                sender_id="coordinator",
                target_id=synthesizer.id,
                message_type=MessageType.REQUEST,
                content=f"Synthesize a final consensus from these positions:\n" + "\n---\n".join(all_texts),
            ))
            output = synthesis.content if synthesis else all_texts[0] if all_texts else ""
        else:
            output = all_texts[0] if all_texts else ""

        return SwarmResult(
            output=output,
            agent_outputs=agent_outputs,
            execution_time_ms=(time.time() - start) * 1000,
            rounds=rounds,
        )

    async def hierarchical(self, task: str, leader: AgentNode,
                           subtask_map: dict[str, list[AgentNode]],
                           metadata: dict | None = None) -> SwarmResult:
        start = time.time()
        agent_outputs: dict[str, str] = {}

        async def execute_group(group_task: str, agents: list[AgentNode]) -> str:
            results = []
            for agent in agents:
                result = await agent.handle_message(MeshMessage(
                    sender_id=leader.id,
                    target_id=agent.id,
                    message_type=MessageType.DELEGATE,
                    content=group_task,
                    metadata=metadata or {},
                ))
                agent_outputs[agent.id] = result.content if result else ""
                results.append(result.content if result else "")
            return "\n".join(results)

        group_results = {}
        for subtask_name, agents in subtask_map.items():
            group_results[subtask_name] = await execute_group(subtask_name, agents)

        final = await leader.handle_message(MeshMessage(
            sender_id="coordinator",
            target_id=leader.id,
            message_type=MessageType.REQUEST,
            content=f"Task: {task}\n\nSubtask results:\n" + "\n".join(
                f"=== {name} ===\n{res}" for name, res in group_results.items()
            ) + "\n\nSynthesize the final result.",
        ))
        output = final.content if final else ""

        return SwarmResult(
            output=output,
            agent_outputs=agent_outputs,
            execution_time_ms=(time.time() - start) * 1000,
            rounds=1,
        )

    async def collaborative(self, task: str, agents: list[AgentNode],
                            breakdown: list[str] | None = None) -> SwarmResult:
        start = time.time()
        if not breakdown:
            breakdown = [f"Part {i + 1} of: {task}" for i in range(len(agents))]

        agent_outputs: dict[str, str] = {}
        contributions = {}

        tasks = []
        for i, agent in enumerate(agents[:len(breakdown)]):
            subtask = breakdown[i] if i < len(breakdown) else task
            tasks.append((agent, subtask))

        async def work(agent: AgentNode, subtask: str) -> tuple[str, str]:
            result = await agent.handle_message(MeshMessage(
                sender_id="coordinator",
                target_id=agent.id,
                message_type=MessageType.REQUEST,
                content=subtask,
            ))
            return agent.id, result.content if result else ""

        results = await asyncio.gather(*[work(a, s) for a, s in tasks], return_exceptions=True)
        for r in results:
            if isinstance(r, tuple):
                agent_id, content = r
                agent_outputs[agent_id] = content
                contributions[agent_id] = content
            elif isinstance(r, Exception):
                logger.error(f"Collaborative swarm error: {r}")

        contributor = agents[0] if agents else None
        if contributor and len(contributions) > 1:
            assembly = await contributor.handle_message(MeshMessage(
                sender_id="coordinator",
                target_id=contributor.id,
                message_type=MessageType.REQUEST,
                content=f"Assemble these contributions into a coherent result:\n{task}\n\n" + "\n".join(
                    f"From {aid}:\n{cont}" for aid, cont in contributions.items()
                ),
            ))
            output = assembly.content if assembly else ""
        else:
            output = list(contributions.values())[0] if contributions else ""

        return SwarmResult(
            output=output,
            agent_outputs=agent_outputs,
            execution_time_ms=(time.time() - start) * 1000,
            rounds=1,
        )

    async def competitive(self, task: str, agents: list[AgentNode],
                          num_winners: int = 1) -> SwarmResult:
        start = time.time()
        agent_outputs: dict[str, str] = {}

        async def compete(agent: AgentNode) -> tuple[str, str]:
            result = await agent.handle_message(MeshMessage(
                sender_id="coordinator",
                target_id=agent.id,
                message_type=MessageType.REQUEST,
                content=task,
            ))
            return agent.id, result.content if result else ""

        results = await asyncio.gather(*[compete(a) for a in agents], return_exceptions=True)
        entries: list[tuple[str, str]] = []
        for r in results:
            if isinstance(r, tuple):
                agent_id, content = r
                agent_outputs[agent_id] = content
                entries.append((agent_id, content))

        if len(entries) <= 1:
            output = entries[0][1] if entries else ""
        else:
            judge = agents[0]
            entries_text = "\n\n".join(
                f"Entry {i + 1} by {a_id}:\n{content}" for i, (a_id, content) in enumerate(entries)
            )
            verdict = await judge.handle_message(MeshMessage(
                sender_id="coordinator",
                target_id=judge.id,
                message_type=MessageType.REQUEST,
                content=f"Judge these solutions for: {task}\n\n{entries_text}\n\n"
                        f"Return the best solution. Output ONLY the winning solution.",
            ))
            output = verdict.content if verdict else entries[0][1]

        return SwarmResult(
            output=output,
            agent_outputs=agent_outputs,
            execution_time_ms=(time.time() - start) * 1000,
            rounds=1,
        )
