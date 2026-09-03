from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# launch_via = Literal('Event','Fork') # add more types.


# region For LLM OUTPUT
class outputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output: str = Field(description="Values or asked arguments to resolve")
    call_number: str | None = Field(
        default=None, description="Value of call_number either an int like 2003 or None"
    )


class outputModelForReturn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output: Literal["READF", "WRITEF", "UNRESOLVED"] = Field(
        description="What is being done with the return pointer of the function."
    )
    call_number: str | None = Field(
        default=None, description="Value of the call_number like 2003 or None"
    )


class TransferEvidenceModel(BaseModel):
    """The exact source line(s) the model cited for one local value transfer.

    The model is never asked for byte offsets: an LLM cannot count bytes
    reliably, and a verbatim snippet is both easier to produce and easier to
    verify -- the resolver locates the snippet in the file itself and derives
    the span.  Old answers that still carry start_byte/end_byte are accepted
    and the stale fields are ignored.
    """

    model_config = ConfigDict(extra="ignore")
    file: str
    snippet: str = ""


class TransferBindingModel(BaseModel):
    """One requested target argument at a selected local call."""

    model_config = ConfigDict(extra="forbid")
    target_arg: int = Field(ge=1)
    kind: Literal["EXPRESSION", "EXTERNAL", "UNKNOWN"]
    expression: str


class TransferArmModel(BaseModel):
    """One correlated, optionally guarded local transfer alternative."""

    model_config = ConfigDict(extra="forbid")
    bindings: list[TransferBindingModel]
    guard: str = "true"
    evidence: list[TransferEvidenceModel]


class TransferAnswerModel(BaseModel):
    """Strict structured output for a demand-driven value transfer."""

    model_config = ConfigDict(extra="forbid")
    arms: list[TransferArmModel]

    @model_validator(mode="after")
    def validate_arms(self) -> "TransferAnswerModel":
        if not self.arms:
            raise ValueError("transfer answer must contain at least one arm")
        return self


# endregion
class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path_str: str = Field(
        description="Will contain the call_graph string to distinguish between different path values."
    )
    ans: list[int | str | Literal["UNRESOLVED", "NO TARGET"]] = Field(
        description="The args resolved."
    )


class Src(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path = Field(description="Path of the file")
    line_number: str = Field(description="line_number")


class aiDetermined(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_number: int | None | str = Field(
        description="The value of the event number as the first argument of the pmf_addevent fn or pmf_addvarevt if present."
    )
    target_number: Target | None = Field(
        description="This will contain the values resolved of the arguments."
    )


class Combined(aiDetermined):
    model_config = ConfigDict(extra="forbid")
    process_name: str = Field(description="The name of the project")
    launch_via: Literal[
        "EVENT",
        "FORK",
        "SEMAPHORE",
        "MESSAGE",
        "TIMER",
        "FORKP",
        "INPUT",
        "SIGNAL",
        "NO DATA",
    ] = Field(
        description="If there's an callback function involved then Event else Fork"
    )
    reachability: str = Field(
        default="UNKNOWN",
        description="How target call is reached, separate from launch metadata.",
    )
    call_function: str = Field(
        description="Function that actually intiated the call usually main and in case of events the function passed as event"
    )
    function_name: str = Field(
        description="The name of the function that we are currently looking for..."
    )
    type: Literal[
        "OPENF",
        "READF",
        "WRITEF",
        "COPYF",
        "SAVEF",
        "LOADF",
        "CLEARF",
        "ENQ",
        "DEQ",
        "READQ",
        "WRITEQ",
        "USEQ",
        "SAVEQ",
        "LOADQ",
        "CLEARQ",
        "CLOSEF",
        # build-index registry family names (target_specs/build_index_targets.json)
        "OPENMF",
        "RECF",
        "QUEUEF",
        "FORKF",
        "NOT_FILE_OR_QUEUE_OP",
        "EVENT",
        "MESSAGE",
        "FORK",
        "SEMAPHORE",
        "KILL",
        "FORKP",
        "MESSAGE",
        "ENQFORK",
        "ENQSEM",
        # Configured by SIGNAL/INPUT registrars; previously missing here even
        # though launch_via already accepted both.
        "SIGNAL",
        "INPUT",
        "NO DATA",
        "UNRESOLVED",
    ] = Field(description="Type of operation.")
    function_name_src: Src
    target_name_src: Src


# region stats model
class TokenCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Input_tokens: int = Field(
        description="The count of all input tokens in all iterations"
    )
    Output_tokens: int = Field(description="Count of output tokens")
    Total_tokens: int = Field(description="Total count of tokens")


class FunctionTokenCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    function_name: str = Field(
        description="Function name for which token counts are mentioned."
    )
    Total_Input: int = Field(description="Total inp. tokens")
    Total_Output: int = Field(description="Total output tokens")
    Total_Tokens: int = Field(description="Total count")
    Each_Path_Tokens: list[dict[int, TokenCount]] = Field(
        description="For each path TokenCount."
    )  # path number and path TokenCount


class Stats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Iterations: int = Field(
        description="Total number of iterations required to conclude to the answer."
    )
    Random_tool_calls: int = Field(
        description="When the models halucinates and calls models with random names that are not provided. Rare but happens sometimes."
    )
    Other_tool_errors: int = Field(
        description="Will have the errors that are caused in the tool but not by llm"
    )
    Incorrect_details: list = Field(
        description="Will contain the details of all the errors whether done by llm or tool errors"
    )
    Tokens: TokenCount = Field(description="Token count info..")


# endregion
