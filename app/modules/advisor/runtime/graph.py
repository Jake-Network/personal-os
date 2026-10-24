"""Bounded, resumable consultation graph; all writes remain in app services.

Node behavior lives in ``runtime/nodes``; this module only wires the graph.
"""
from langgraph.graph import END, START, StateGraph

from app.modules.advisor.runtime.adapters import GatewayChatModel, read_tools
from app.modules.advisor.runtime.context import ContextAssembler
from app.modules.advisor.runtime.nodes.analysis import analyze, review
from app.modules.advisor.runtime.nodes.answer import finish
from app.modules.advisor.runtime.nodes.base import NodeContext, bind, structured_response  # noqa: F401
from app.modules.advisor.runtime.nodes.data_commands import data_commands
from app.modules.advisor.runtime.nodes.planning import clarify, plan, summarize
from app.modules.advisor.runtime.nodes.research import collected, dispatch, pending_tasks, research, web_research
from app.modules.advisor.runtime.numeric_guard import numeric_values, validated_numeric_answer  # noqa: F401
from app.modules.advisor.runtime.schemas import (DataCommand, DataCommandPlan, FinalAnswer,  # noqa: F401
    HistorySummary, Memory, Plan, Proposal, Question, ResearchTask, Review, Scenario, StrictModel)
from app.modules.advisor.runtime.state import (ConsultationState, initial_state, needs_analysis,  # noqa: F401
    quantitative_followup, scenario_followup)


def build_conversation_graph(session, manager, conversation, options, model, checkpointer=None,
                             guard=None, current_message_id=None, on_progress=None, run_authorization=None,
                             on_stream=None, command_guard=None, on_data_operations=None,
                             recorded_operations=None, recorded_command_plan=None,
                             recorded_command_query=None, recorded_command_source_ids=None,
                             run_id=None, run_owner=None, run_generation=None, data_commands_allowed=True, on_quote_refresh=None):
    assembler = ContextAssembler(session, manager, conversation, options, model,
                                 guard=guard, current_message_id=current_message_id, authorization=run_authorization, run_id=run_id,
                                 run_owner=run_owner, run_generation=run_generation)
    ctx = NodeContext(session=session, manager=manager, conversation=conversation, options=options,
                      assembler=assembler, tools=read_tools(assembler), chat_model=GatewayChatModel,
                      current_message_id=current_message_id, on_progress=on_progress, on_stream=on_stream,
                      command_guard=command_guard, on_data_operations=on_data_operations,
                      recorded_operations=recorded_operations, recorded_command_plan=recorded_command_plan,
                      recorded_command_query=recorded_command_query,
                      recorded_command_source_ids=recorded_command_source_ids,
                      data_commands_allowed=data_commands_allowed, on_quote_refresh=on_quote_refresh)

    def route_analysis(state):
        return 'finish' if state.get('single_response') or not needs_analysis(state) else 'summarize'

    graph = StateGraph(ConsultationState)
    for name, node in [('data_commands', data_commands), ('summarize', summarize), ('plan', plan), ('clarify', clarify), ('research', research),
                       ('collected', collected), ('analyze', analyze), ('review', review), ('finish', finish),
                       ('web_search', web_research)]:
        graph.add_node(name, bind(node, ctx))
    graph.add_edge(START, 'data_commands')
    graph.add_conditional_edges('data_commands', lambda state: 'web_search' if getattr(options, 'web_search', False) else route_analysis(state))
    graph.add_conditional_edges('web_search', route_analysis)
    graph.add_edge('summarize', 'plan')
    graph.add_conditional_edges('plan', lambda state: 'clarify' if state.get('clarification') else 'collected')
    graph.add_edge('clarify', 'plan')
    graph.add_conditional_edges('collected', dispatch)
    graph.add_edge('research', 'collected')
    graph.add_conditional_edges('analyze', lambda state: 'review' if state.get('depth') == 'deep' else 'finish')
    graph.add_conditional_edges('review', lambda state: 'plan' if state.get('needs_replan') else
                                'collected' if pending_tasks(state) else 'finish')
    graph.add_edge('finish', END)
    return graph.compile(checkpointer=checkpointer, store=getattr(assembler, 'memory_store', None))
