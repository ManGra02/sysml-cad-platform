"""Where the LLM is and which model each project uses.

Only Ollama Cloud is supported. Settings come from environment variables,
falling back to backend/.env (gitignored; template: backend/.env.example):

  OLLAMA_API_KEY        API key from https://ollama.com/settings/keys (required)
  OLLAMA_BASE_URL       default https://ollama.com
  OLLAMA_MODEL          default model for every project, e.g. gpt-oss:120b
  OLLAMA_MODEL_<ID>     model for one project, overrides OLLAMA_MODEL --
                        <ID> is the module id in upper case: OLLAMA_MODEL_BDS, OLLAMA_MODEL_CRA
  OLLAMA_TIMEOUT_S      timeout per LLM request in seconds (default 120)
  OLLAMA_STATUS_TTL_S   how long a status check is reused (default 30)

Without a key the platform runs as usual; /api/ai/status reports
"not configured" and ``ctx.ai`` raises AiError(503, "ai_not_configured").
"""

import os
from dataclasses import dataclass, field

from app import config

MODEL_PREFIX = "OLLAMA_MODEL_"


@dataclass
class AiConfig:
    api_key: str | None = None
    base_url: str = "https://ollama.com"
    default_model: str | None = None
    #: module id -> model name
    models: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 120.0
    status_ttl_s: float = 30.0

    @classmethod
    def from_env(cls, env_file=None):
        values = {**config.read_env_file(env_file or config.ENV_FILE), **os.environ}
        return cls(
            api_key=values.get("OLLAMA_API_KEY") or None,
            base_url=(values.get("OLLAMA_BASE_URL") or cls.base_url).rstrip("/"),
            default_model=values.get("OLLAMA_MODEL") or None,
            models={key[len(MODEL_PREFIX):].lower(): value
                    for key, value in values.items() if key.startswith(MODEL_PREFIX) and value},
            timeout_s=float(values.get("OLLAMA_TIMEOUT_S") or cls.timeout_s),
            status_ttl_s=float(values.get("OLLAMA_STATUS_TTL_S") or cls.status_ttl_s),
        )

    @property
    def configured(self):
        return bool(self.api_key)

    def model_for(self, module_id):
        """The project's own model, otherwise the default -- None if neither is set."""
        return self.models.get(module_id.lower()) or self.default_model

    def headers(self):
        return {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
