from fastapi import APIRouter, HTTPException

from orchestra.code_agent.agentmesh import (
    AgentRegistry, AgentInfo, AgentType, AgentStatus,
    AgentNode, MeshNetwork, MeshMessage, MessageType,
)


_mesh: MeshNetwork | None = None


def get_mesh() -> MeshNetwork:
    global _mesh
    if _mesh is None:
        _mesh = MeshNetwork()
    return _mesh


def register_agentmesh_routes(app, prefix: str = "/api/agentmesh"):
    mesh = get_mesh()
    router = APIRouter(prefix=prefix)

    @router.post("/agents/register")
    async def register_agent(body: dict):
        required = ["name", "agent_type"]
        for field in required:
            if field not in body:
                raise HTTPException(400, f"Missing required field: {field}")
        info = AgentInfo(
            name=body["name"],
            agent_type=AgentType(body.get("agent_type", "general")),
            capabilities=body.get("capabilities", []),
            status=AgentStatus.ONLINE,
            llm_model=body.get("llm_model", ""),
            max_concurrent_tasks=body.get("max_concurrent_tasks", 1),
            tags=body.get("tags", []),
            metadata=body.get("metadata", {}),
        )
        node = AgentNode(info)
        await node.start(mesh.registry)
        mesh.register_node(node)
        return {"agent_id": info.id, "status": "registered"}

    @router.get("/agents")
    async def list_agents(status: str | None = None):
        if status:
            agents = mesh.registry.list_by_status(AgentStatus(status))
        else:
            agents = mesh.registry.list_agents()
        return {"agents": [a.__dict__ for a in agents], "count": len(agents)}

    @router.get("/agents/{agent_id}")
    async def get_agent(agent_id: str):
        info = mesh.registry.get(agent_id)
        if not info:
            raise HTTPException(404, "Agent not found")
        result = info.__dict__
        result["is_available"] = info.is_available()
        result["load_pct"] = info.load_pct
        return result

    @router.delete("/agents/{agent_id}")
    async def unregister_agent(agent_id: str):
        node = mesh.get_node(agent_id)
        if node:
            await node.stop(mesh.registry)
        mesh.unregister_node(agent_id)
        return {"status": "unregistered"}

    @router.post("/agents/{agent_id}/heartbeat")
    async def agent_heartbeat(agent_id: str, body: dict = {}):
        status = body.get("status")
        status_enum = AgentStatus(status) if status else None
        ok = mesh.registry.heartbeat(agent_id, status_enum)
        if not ok:
            raise HTTPException(404, "Agent not found")
        return {"status": "ok"}

    @router.post("/discover")
    async def discover_agents(body: dict):
        capability = body.get("capability")
        agent_type = body.get("agent_type")
        tag = body.get("tag")
        available_only = body.get("available_only", True)
        if capability:
            agents = mesh.registry.discover_by_capability(capability, available_only)
        elif agent_type:
            agents = mesh.registry.discover_by_type(AgentType(agent_type), available_only)
        elif tag:
            agents = mesh.registry.discover_by_tag(tag, available_only)
        else:
            agents = mesh.registry.list_agents()
        return {"agents": [a.__dict__ for a in agents], "count": len(agents)}

    @router.post("/message")
    async def send_message(body: dict):
        msg = MeshMessage(
            sender_id=body.get("sender_id", "api"),
            target_id=body.get("target_id", ""),
            target_capability=body.get("target_capability", ""),
            message_type=MessageType(body.get("message_type", "request")),
            content=body.get("content", ""),
            metadata=body.get("metadata", {}),
        )
        responses = await mesh.send(msg)
        return {
            "sent": True,
            "target_count": len(responses),
            "responses": [r.content for r in responses],
        }

    @router.post("/request")
    async def make_request(body: dict):
        target_id = body.get("target_id", "")
        target_capability = body.get("target_capability", "")
        content = body.get("content", "")
        sender_id = body.get("sender_id", "api")

        if target_capability:
            response = await mesh.request_by_capability(target_capability, content, sender_id)
        elif target_id:
            response = await mesh.request(target_id, content, sender_id)
        else:
            raise HTTPException(400, "Provide target_id or target_capability")
        if response is None:
            return {"response": None, "error": "No available agent found"}
        return {"response": response.content, "sender_id": response.sender_id}

    @router.get("/health")
    async def health():
        return await mesh.health()

    @router.get("/traces")
    async def list_traces():
        traces = mesh.get_all_traces()
        return {"traces": {k: [m.__dict__ for m in v] for k, v in traces.items()}, "count": len(traces)}

    @router.get("/traces/{trace_id}")
    async def get_trace(trace_id: str):
        trace = mesh.get_trace(trace_id)
        return {"trace_id": trace_id, "messages": [m.__dict__ for m in trace]}

    app.include_router(router)
