from pydantic import BaseModel, Field

class AgentAction(BaseModel):
    """
    Structured action protocol for the ReAct Agent Loop.
    Enforces that the LLM output is parsed as validated JSON.
    """
    intent: str = Field(description="The thought or reasoning for this step.")
    tool: str | None = Field(None, description="The name of the tool to execute. null if no action is needed.")
    args: dict = Field(default_factory=dict, description="Arguments to pass to the tool.")
    requires_confirmation: bool = Field(False, description="True if this tool requires human-in-the-loop confirmation.")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence score for this action.")
