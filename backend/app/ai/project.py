"""``self.ctx.ai`` -- one module's access to the LLM, bound to that module's model.

    llm = self.ctx.ai.chat_model()                       # a LangChain ChatOllama
    answer = await llm.ainvoke("Summarise: ...")

    agent = self.ctx.ai.agent(tools, prompt="You are ...")   # a compiled LangGraph graph
    result = await run(agent, "question")                 # app.ai.agents.run

Anything LangChain/LangGraph can do with a chat model works with chat_model(),
e.g. your own StateGraph, structured output (llm.with_structured_output(Schema))
or streaming (llm.astream(...)).
"""

from app.ai.client import AiError


class ProjectAi:
    def __init__(self, module_id, config):
        self.module_id = module_id
        self.config = config

    @property
    def model(self):
        """The model this project uses (OLLAMA_MODEL_<ID>, otherwise OLLAMA_MODEL)."""
        return self.config.model_for(self.module_id)

    @property
    def configured(self):
        return self.config.configured and bool(self.model)

    def chat_model(self, model=None, **kwargs):
        """A ChatOllama against Ollama Cloud. ``model`` overrides the project's model for one use;
        further kwargs go to ChatOllama (temperature, num_ctx, reasoning, format, ...)."""
        # Imported on first use: LangChain/LangGraph take seconds to import, the backend starts without them.
        from langchain_ollama import ChatOllama

        if not self.config.configured:
            raise AiError(503, "ai_not_configured",
                          "No Ollama API key configured (OLLAMA_API_KEY in backend/.env)")
        name = model or self.model
        if not name:
            raise AiError(503, "ai_no_model",
                          "No model configured for project %r (OLLAMA_MODEL_%s or OLLAMA_MODEL)"
                          % (self.module_id, self.module_id.upper()))
        return ChatOllama(
            model=name,
            base_url=self.config.base_url,
            client_kwargs={"headers": self.config.headers(), "timeout": self.config.timeout_s},
            **kwargs,
        )

    def agent(self, tools, prompt=None, model=None, **kwargs):
        """A tool-calling agent (LangGraph) on the project's model -- see agents.react_agent."""
        from app.ai.agents import react_agent

        return react_agent(self.chat_model(model=model, **kwargs), tools, prompt=prompt)
