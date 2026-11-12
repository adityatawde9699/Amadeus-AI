"""
Building blocks of the LangGraph agent (``AmadeusGraph``).

``src/app/services/agent_loop.py`` stays the public entry point; the graph's
node implementations live here as mixins:

* ``state``         — ``AmadeusState``, ``AgentResult``, ``AgentStep``, ``QueueFullError``
* ``actions``       — JSON parsing, math extraction, approval / taint rules
* ``outcomes``      — reflective learning (past tool outcomes)
* ``orchestration`` — orchestrator, supervisor, collection, synthesis + routers
* ``expert``        — expert plan → tool → reflect nodes
"""
