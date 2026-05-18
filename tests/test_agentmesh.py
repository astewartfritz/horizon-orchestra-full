import pytest
import time
import asyncio

from code_agent.agentmesh import (
    AgentRegistry, AgentInfo, AgentType, AgentStatus,
    AgentNode, MeshNetwork, MeshRouter, MeshMessage, MessageType,
)


class TestAgentRegistry:
    def test_register(self):
        r = AgentRegistry()
        info = AgentInfo(name="test-agent", agent_type=AgentType.GENERAL, capabilities=["coding"])
        aid = r.register(info)
        assert r.get(aid) is info
        assert aid == info.id

    def test_unregister(self):
        r = AgentRegistry()
        info = AgentInfo(name="test", capabilities=["coding"])
        aid = r.register(info)
        assert r.unregister(aid) is True
        assert r.get(aid) is None
        assert r.unregister("nonexistent") is False

    def test_discover_by_capability(self):
        r = AgentRegistry()
        a1 = AgentInfo(name="coder1", capabilities=["coding", "debugging"], status=AgentStatus.ONLINE, max_concurrent_tasks=2)
        a2 = AgentInfo(name="coder2", capabilities=["coding"], status=AgentStatus.ONLINE, max_concurrent_tasks=2)
        a3 = AgentInfo(name="writer", capabilities=["writing"], status=AgentStatus.ONLINE, max_concurrent_tasks=2)
        r.register(a1)
        r.register(a2)
        r.register(a3)
        coders = r.discover_by_capability("coding")
        assert len(coders) == 2
        writers = r.discover_by_capability("writing")
        assert len(writers) == 1
        none = r.discover_by_capability("research")
        assert len(none) == 0

    def test_discover_by_type(self):
        r = AgentRegistry()
        a1 = AgentInfo(name="a1", agent_type=AgentType.CODER, status=AgentStatus.ONLINE)
        a2 = AgentInfo(name="a2", agent_type=AgentType.CODER, status=AgentStatus.ONLINE)
        a3 = AgentInfo(name="a3", agent_type=AgentType.REASONER, status=AgentStatus.ONLINE)
        r.register(a1)
        r.register(a2)
        r.register(a3)
        coders = r.discover_by_type(AgentType.CODER)
        assert len(coders) == 2
        reasoners = r.discover_by_type(AgentType.REASONER)
        assert len(reasoners) == 1

    def test_discover_available_only(self):
        r = AgentRegistry()
        a1 = AgentInfo(name="busy", capabilities=["coding"], status=AgentStatus.BUSY, max_concurrent_tasks=2, current_tasks=2)
        a2 = AgentInfo(name="free", capabilities=["coding"], status=AgentStatus.ONLINE, max_concurrent_tasks=2)
        r.register(a1)
        r.register(a2)
        available = r.discover_by_capability("coding", available_only=True)
        assert len(available) == 1
        assert available[0].name == "free"
        all_coders = r.discover_by_capability("coding", available_only=False)
        assert len(all_coders) == 2

    def test_heartbeat(self):
        r = AgentRegistry()
        info = AgentInfo(name="hb", status=AgentStatus.ONLINE)
        aid = r.register(info)
        assert r.heartbeat(aid, AgentStatus.BUSY) is True
        assert r.get(aid).status == AgentStatus.BUSY
        assert r.heartbeat("nonexistent") is False

    def test_evict_stale(self):
        r = AgentRegistry()
        info = AgentInfo(name="stale")
        aid = r.register(info)
        info.last_heartbeat = time.time() - 120
        evicted = r.evict_stale(max_age=60.0)
        assert aid in evicted
        assert r.get(aid) is None

    def test_discover_multi_capability(self):
        r = AgentRegistry()
        a1 = AgentInfo(name="a1", capabilities=["coding", "debugging"], status=AgentStatus.ONLINE, max_concurrent_tasks=2)
        a2 = AgentInfo(name="a2", capabilities=["coding"], status=AgentStatus.ONLINE, max_concurrent_tasks=2)
        r.register(a1)
        r.register(a2)
        both = r.discover_multi_capability(["coding", "debugging"], require_all=True)
        assert len(both) == 1
        assert both[0].name == "a1"
        any_cap = r.discover_multi_capability(["coding", "debugging"], require_all=False)
        assert len(any_cap) == 2

    def test_callbacks(self):
        r = AgentRegistry()
        events = []
        r.on_register(lambda inf: events.append(("register", inf.name)))
        r.on_unregister(lambda inf: events.append(("unregister", inf.name)))
        r.on_status_change(lambda inf, old, new: events.append(("status", inf.name, old, new)))
        info = AgentInfo(name="cb-agent", status=AgentStatus.ONLINE)
        aid = r.register(info)
        r.heartbeat(aid, AgentStatus.BUSY)
        r.unregister(aid)
        assert ("register", "cb-agent") in events
        assert ("unregister", "cb-agent") in events

    def test_list_by_status(self):
        r = AgentRegistry()
        r.register(AgentInfo(name="a", status=AgentStatus.ONLINE))
        r.register(AgentInfo(name="b", status=AgentStatus.BUSY))
        r.register(AgentInfo(name="c", status=AgentStatus.ONLINE))
        online = r.list_by_status(AgentStatus.ONLINE)
        assert len(online) == 2
        busy = r.list_by_status(AgentStatus.BUSY)
        assert len(busy) == 1

    def test_available_count(self):
        r = AgentRegistry()
        r.register(AgentInfo(name="a", status=AgentStatus.ONLINE))
        r.register(AgentInfo(name="b", status=AgentStatus.BUSY, max_concurrent_tasks=2, current_tasks=2))
        r.register(AgentInfo(name="c", status=AgentStatus.ONLINE))
        assert r.available_count() == 2

    def test_is_available(self):
        info = AgentInfo(name="test", status=AgentStatus.ONLINE, max_concurrent_tasks=3, current_tasks=1)
        assert info.is_available() is True
        info.current_tasks = 3
        assert info.is_available() is False
        info.status = AgentStatus.BUSY
        assert info.is_available() is False

    def test_tags(self):
        r = AgentRegistry()
        a1 = AgentInfo(name="t1", tags=["gpu", "fast"], status=AgentStatus.ONLINE)
        a2 = AgentInfo(name="t2", tags=["gpu"], status=AgentStatus.ONLINE)
        r.register(a1)
        r.register(a2)
        gpu = r.discover_by_tag("gpu")
        assert len(gpu) == 2
        fast = r.discover_by_tag("fast")
        assert len(fast) == 1


class TestAgentNode:
    @pytest.mark.asyncio
    async def test_handle_request(self):
        info = AgentInfo(name="echo", agent_type=AgentType.GENERAL)
        node = AgentNode(info)
        node.set_llm_function(lambda content, meta: f"Echo: {content}")
        msg = MeshMessage(
            sender_id="test",
            target_id=node.id,
            message_type=MessageType.REQUEST,
            content="hello",
        )
        response = await node.handle_message(msg)
        assert response is not None
        assert response.content == "Echo: hello"
        assert response.message_type == MessageType.RESPONSE
        assert response.parent_id == msg.id

    @pytest.mark.asyncio
    async def test_handle_heartbeat(self):
        info = AgentInfo(name="hb-node")
        node = AgentNode(info)
        msg = MeshMessage(
            sender_id="test",
            target_id=node.id,
            message_type=MessageType.HEARTBEAT,
            content="ping",
        )
        response = await node.handle_message(msg)
        assert response is not None
        assert response.content == "alive"
        assert response.message_type == MessageType.HEARTBEAT

    @pytest.mark.asyncio
    async def test_handler_registration(self):
        info = AgentInfo(name="handler-test")
        node = AgentNode(info)
        handled = []

        def custom_handler(n, msg):
            handled.append(msg.content)
            return MeshMessage(
                sender_id=n.id,
                target_id=msg.sender_id,
                message_type=MessageType.RESPONSE,
                content="custom",
            )

        node.on_message(MessageType.REQUEST, custom_handler)
        msg = MeshMessage(content="test-req", message_type=MessageType.REQUEST)
        response = await node.handle_message(msg)
        assert response.content == "custom"
        assert "test-req" in handled

    @pytest.mark.asyncio
    async def test_start_stop(self):
        r = AgentRegistry()
        info = AgentInfo(name="lifecycle", status=AgentStatus.OFFLINE)
        node = AgentNode(info)
        await node.start(r)
        assert r.get(node.id).status == AgentStatus.ONLINE
        await node.stop(r)
        assert r.get(node.id).status == AgentStatus.OFFLINE


class TestMeshNetwork:
    @pytest.mark.asyncio
    async def test_send_and_route(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        node1 = AgentNode(AgentInfo(name="node1", capabilities=["coding"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
        node2 = AgentNode(AgentInfo(name="node2", capabilities=["analysis"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
        node1.set_llm_function(lambda c, m: f"Node1: {c}")
        node2.set_llm_function(lambda c, m: f"Node2: {c}")
        network.register_node(node1)
        network.register_node(node2)
        await network.start()

        responses = await network.send(MeshMessage(
            sender_id="coord",
            target_capability="coding",
            content="do something",
        ))
        assert len(responses) > 0
        await network.stop()

    @pytest.mark.asyncio
    async def test_request_response(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        node = AgentNode(AgentInfo(name="responder", capabilities=["general"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
        node.set_llm_function(lambda c, m: f"Response to: {c}")
        network.register_node(node)
        await network.start()

        response = await network.request(node.id, "hello world", "requester")
        assert response is not None
        assert response.content == "Response to: hello world"
        await network.stop()

    @pytest.mark.asyncio
    async def test_request_by_capability(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        node = AgentNode(AgentInfo(name="coder", capabilities=["coding", "general"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
        node2 = AgentNode(AgentInfo(name="writer", capabilities=["writing"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
        node.set_llm_function(lambda c, m: f"code: {c}")
        node2.set_llm_function(lambda c, m: f"write: {c}")
        network.register_node(node)
        network.register_node(node2)
        await network.start()

        response = await network.request_by_capability("coding", "write a function", "coord")
        assert response is not None
        assert response.content.startswith("code:")
        await network.stop()

    @pytest.mark.asyncio
    async def test_broadcast(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        nodes = []
        for i in range(3):
            n = AgentNode(AgentInfo(name=f"node-{i}", capabilities=["general"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
            n.set_llm_function(lambda c, m: f"received: {c}")
            network.register_node(n)
            nodes.append(n)
        await network.start()

        responses = await network.broadcast(MeshMessage(sender_id="coord", content="broadcast test"))
        assert len(responses) <= 3
        await network.stop()

    @pytest.mark.asyncio
    async def test_health(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        node = AgentNode(AgentInfo(name="h", status=AgentStatus.ONLINE))
        network.register_node(node)
        await network.start()
        health = await network.health()
        assert health["total_nodes"] == 1
        assert health["online"] == 1
        await network.stop()

    @pytest.mark.asyncio
    async def test_trace_storage(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        msg = MeshMessage(sender_id="s1", target_id="t1", content="trace me", trace_id="trace-1")
        network._trace(msg)
        trace = network.get_trace("trace-1")
        assert len(trace) == 1
        assert trace[0].content == "trace me"

    @pytest.mark.asyncio
    async def test_delegate(self):
        registry = AgentRegistry()
        network = MeshNetwork(registry)
        node = AgentNode(AgentInfo(name="worker", capabilities=["general"], status=AgentStatus.ONLINE, max_concurrent_tasks=2))
        node.set_llm_function(lambda c, m: f"delegated: {c}")
        network.register_node(node)
        await network.start()
        response = await network.delegate(node.id, "do work", "manager", {"key": "val"})
        assert response is not None
        assert response.content == "delegated: do work"
        await network.stop()

    @pytest.mark.asyncio
    async def test_mesh_router(self):
        registry = AgentRegistry()
        router = MeshRouter(registry)
        nodes = {}
        msg = MeshMessage(sender_id="s", target_capability="test-cap")
        result = await router.route(msg, nodes)
        assert result == []


class TestMeshMessage:
    def test_message_creation(self):
        msg = MeshMessage(sender_id="s1", target_id="t1", content="hello", message_type=MessageType.REQUEST)
        assert msg.id
        assert msg.sender_id == "s1"
        assert msg.target_id == "t1"
        assert msg.content == "hello"
        assert msg.message_type == MessageType.REQUEST
        assert msg.timestamp > 0

    def test_is_broadcast(self):
        broadcast = MeshMessage(message_type=MessageType.BROADCAST)
        assert broadcast.is_broadcast() is True
        no_target = MeshMessage(sender_id="s")
        assert no_target.is_broadcast() is True
        direct = MeshMessage(sender_id="s", target_id="t")
        assert direct.is_broadcast() is False

    def test_message_type_values(self):
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.DELEGATE.value == "delegate"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.BROADCAST.value == "broadcast"


class TestAgentInfo:
    def test_load_pct(self):
        info = AgentInfo(max_concurrent_tasks=4, current_tasks=1)
        assert info.load_pct == 0.25
        info.max_concurrent_tasks = 0
        assert info.load_pct == 1.0
