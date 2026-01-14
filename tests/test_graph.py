import pytest
import asyncio
from unittest.mock import MagicMock
import sys

# Mock chainlit before importing nodes
mock_cl = MagicMock()

def mock_make_async(f):
    async def wrapper(*args, **kwargs):
        # Handle both sync and async functions if needed
        import inspect
        if inspect.iscoroutinefunction(f):
            return await f(*args, **kwargs)
        return f(*args, **kwargs)
    return wrapper

mock_cl.make_async = mock_make_async
mock_cl.user_session = MagicMock()
sys.modules["chainlit"] = mock_cl

from services.graph import chatbot_graph
from services.graph_state import AgentState

@pytest.mark.asyncio
async def test_graph_router_greeting():
    # Initial State
    initial_state = {
        "question": "Hola",
        "history": [],
        "router_state": {},
        "thinking_message_id": "test_id",
        "intent": None,
        "answer": None,
        "error": None,
        "sidebar_title": None,
        "sidebar_md": None,
        "sidebar_props": None,
        "follow_ups": None,
        "element_to_send": None,
        "answer_prompt": None,
        "ppt_generation_input": None
    }
    
    # Execute Graph
    final_state = await chatbot_graph.ainvoke(initial_state)
    print(f"\nDEBUG FINAL STATE: {final_state}")
    
    assert final_state["intent"]["is_greeting"] is True
    assert "Hola" in final_state["answer"]
    assert final_state["error"] is None

@pytest.mark.asyncio
async def test_graph_router_unknown():
    # Initial State
    initial_state = {
        "question": "Cuéntame un chiste",
        "history": [],
        "router_state": {},
        "thinking_message_id": "test_id",
        "intent": None,
        "answer": None,
        "error": None,
        "sidebar_title": None,
        "sidebar_md": None,
        "sidebar_props": None,
        "follow_ups": None,
        "element_to_send": None,
        "answer_prompt": None,
        "ppt_generation_input": None
    }
    
@pytest.mark.asyncio
async def test_graph_entity_switch():
    # 1. Initial Search for Techfriendly
    state_1 = {
        "question": "¿Qué ha ganado Techfriendly?",
        "history": [],
        "router_state": {},
        "thinking_message_id": "t1",
        "intent": None, "answer": None, "error": None,
        "sidebar_title": None, "sidebar_md": None, "sidebar_props": None,
        "follow_ups": None, "element_to_send": None, "answer_prompt": None, "ppt_generation_input": None
    }
    res_1 = await chatbot_graph.ainvoke(state_1)
    assert res_1["intent"]["focus"] == "EMPRESA"
    assert "Techfriendly" in res_1["router_state"]["last_empresa_query"]

    # 2. Follow-up for Vodafone (Entity Switch)
    state_2 = {
        **res_1,
        "question": "y Vodafone?",
        "intent": None, "answer": None, "error": None,
        "answer_prompt": None
    }
    res_2 = await chatbot_graph.ainvoke(state_2)
    assert res_2["intent"]["focus"] == "EMPRESA"
    assert "Vodafone" in res_2["router_state"]["last_empresa_query"]

    # 3. Specific phrasing "y FCC ha ganado?"
    state_3 = {
        **res_2,
        "question": "y FCC ha ganado contratos?",
        "intent": None, "answer": None, "error": None,
        "answer_prompt": None
    }
    res_3 = await chatbot_graph.ainvoke(state_3)
    assert res_3["intent"]["focus"] == "EMPRESA"
    assert "FCC" in res_3["router_state"]["last_empresa_query"]

    # 4. Follow-up "seguro?"
    state_4 = {
        **res_3,
        "question": "seguro?",
        "intent": None, "answer": None, "error": None,
        "answer_prompt": None
    }
    res_4 = await chatbot_graph.ainvoke(state_4)
    # It should remain in focus=EMPRESA and query=FCC
    assert res_4["intent"]["is_followup"] is True
    assert res_4["intent"]["focus"] == "EMPRESA"
    assert "FCC" in res_4["router_state"]["last_empresa_query"]

@pytest.mark.asyncio
async def test_graph_ppt_clarification_strictness():
    # Test broad request that SHOULD trigger clarification
    state = {
        "question": "Generar PPT vehículo 4x4",
        "history": [],
        "router_state": {},
        "thinking_message_id": "test_ppt",
        "intent": {"intent": "GENERATE_PPT", "focus": "CONTRATO"},
        "answer": None, "error": None,
        "sidebar_title": None, "sidebar_md": None, "sidebar_props": None,
        "follow_ups": None, "element_to_send": None, "answer_prompt": None, "ppt_generation_input": None
    }
    
    # We need to manually simulate the router having already run or call the whole graph
    # Let's call the whole graph but the router might classify it differently if not careful
    # Actually ppt_node is what calls plan_ppt_clarifications
    
    res = await chatbot_graph.ainvoke(state)
    
    # Check if intent was updated with ppt_clarifications_needed
    assert res["intent"].get("ppt_clarifications_needed") is True
    assert len(res["intent"]["ppt_plan"]["questions"]) > 0
    assert "aclaraciones" in res["answer"].lower()
@pytest.mark.asyncio
async def test_graph_ppt_leakage_and_topic_switch():
    # 1. Initial PPT request (4x4)
    state_1 = {
        "question": "Me haces un pliego para un vehículo 4x4?",
        "history": [],
        "router_state": {},
        "thinking_message_id": "test_leak",
        "intent": None, "answer": None, "error": None,
        "sidebar_title": None, "sidebar_md": None, "sidebar_props": None,
        "follow_ups": None, "element_to_send": None, "answer_prompt": None, "ppt_generation_input": None
    }
    res_1 = await chatbot_graph.ainvoke(state_1)
    assert res_1["intent"]["intent"] == "GENERATE_PPT"
    assert res_1["intent"]["ppt_clarifications_needed"] is True
    assert "4x4" in res_1["router_state"]["ppt_request_base"].lower()
    
    # 2. Intent switch: RAG query about Vodafone
    state_2 = {
        **res_1,
        "question": "Cuantos contratos ha ganado Vodafone?",
        "intent": None, "answer": None, "error": None, "answer_prompt": None
    }
    res_2 = await chatbot_graph.ainvoke(state_2)
    assert res_2["intent"]["intent"] == "RAG_QA"
    # PPT state should be cleared in router_state
    assert res_2["router_state"].get("ppt_pending") is False
    assert res_2["router_state"].get("ppt_request_base") == ""
    
    # 3. New PPT request: Telephony
    state_3 = {
        **res_2,
        "question": "me haces un PPT de telefonía móvil?",
        "intent": None, "answer": None, "error": None, "answer_prompt": None
    }
    res_3 = await chatbot_graph.ainvoke(state_3)
    assert res_3["intent"]["intent"] == "GENERATE_PPT"
    assert res_3["intent"]["ppt_clarifications_needed"] is True
    # Should NOT have 4x4 in the base request
    assert "4x4" not in res_3["router_state"]["ppt_request_base"].lower()
    assert "telef" in res_3["router_state"]["ppt_request_base"].lower()

@pytest.mark.asyncio
async def test_graph_ppt_technical_answer_persistence():
    # 1. Start PPT request
    state_1 = {
        "question": "Generar PPT totems digitales",
        "history": [],
        "router_state": {},
        "thinking_message_id": "t1",
        "intent": None, "answer": None, "error": None,
        "sidebar_title": None, "sidebar_md": None, "sidebar_props": None,
        "follow_ups": None, "element_to_send": None, "answer_prompt": None, "ppt_generation_input": None
    }
    res_1 = await chatbot_graph.ainvoke(state_1)
    assert res_1["intent"]["intent"] == "GENERATE_PPT"
    assert res_1["router_state"]["ppt_pending"] is True
    assert res_1["router_state"]["ppt_rounds"] == 1
    
    # 2. Provide numbered technical answers
    # Even if "Techfriendly" was in history (simulated context)
    # the router should NOT switch to RAG because of the technical list heuristic
    state_2 = {
        **res_1,
        "question": "1. LED 55 pulgadas\n2. 4K\n3. Linux",
        "intent": None, "answer": None, "error": None, "answer_prompt": None
    }
    # Simulate Techfriendly noise in router_state
    state_2["router_state"]["last_empresa_query"] = "Techfriendly"
    
    res_2 = await chatbot_graph.ainvoke(state_2)
    
    # It should STAY in PPT flow
    assert res_2["intent"]["intent"] == "GENERATE_PPT"
    assert res_2["router_state"]["ppt_pending"] is True
    assert res_2["router_state"]["ppt_rounds"] == 2
    
    # 3. Third round: Should finish even if plan says need_clarification=True (rounds limit)
    state_3 = {
        **res_2,
        "question": "Sí, 3000 nits y garantía de 5 años.",
        "intent": None, "answer": None, "error": None, "answer_prompt": None
    }
    res_3 = await chatbot_graph.ainvoke(state_3)
    
    # Should NOT be pending anymore (ppt_rounds hit limit)
    assert res_3["router_state"]["ppt_pending"] is False
    assert res_3["ppt_generation_input"] is not None

@pytest.mark.asyncio
async def test_graph_ppt_multiline_answer():
    # 1. Start PPT request
    state_1 = {
        "question": "Generar PPT totems digitales",
        "history": [],
        "router_state": {},
        "thinking_message_id": "test_multi",
        "intent": None, "answer": None, "error": None,
        "sidebar_title": None, "sidebar_md": None, "sidebar_props": None,
        "follow_ups": None, "element_to_send": None, "answer_prompt": None, "ppt_generation_input": None
    }
    res_1 = await chatbot_graph.ainvoke(state_1)
    assert res_1["router_state"]["ppt_pending"] is True
    
    # 2. Provide multiline answers WITHOUT explicit bullet points
    # This is what failed in the user's screenshot
    state_2 = {
        **res_1,
        "question": "3000 nits\nsí\ncualquier\n4G es suficiente\nred eléctrica municipal\nno incluye mantenimiento, pero sí garantía de 5 años",
        "intent": None, "answer": None, "error": None, "answer_prompt": None
    }
    # Simulate Techfriendly noise in history
    state_2["router_state"]["last_empresa_query"] = "Techfriendly"
    
    res_2 = await chatbot_graph.ainvoke(state_2)
    
    # It should STAY in PPT flow because it's multiline (>=3 lines)
    assert res_2["intent"]["intent"] == "GENERATE_PPT"
    assert res_2["router_state"]["ppt_pending"] is True
    assert res_2["router_state"]["ppt_rounds"] == 2
