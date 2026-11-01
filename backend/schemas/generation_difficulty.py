"""Private-practice difficulty is advisory, never graduation evidence."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Level = Literal['basic','medium','hard','challenge']
Change = Literal['unspecified','easier','much_easier','similar','harder','much_harder']


class DifficultyRequirement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    raw_text: str = Field(default='',max_length=4000)
    target_level: Level = 'basic'
    relative_change: Change = 'unspecified'
    absolute_explicit: bool = False


class ModelDifficultyAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    estimated_level: Literal['basic','medium','hard','challenge','unknown']
    relative_change: Literal['easier','much_easier','similar','harder','much_harder','unknown']
    reason: str = Field(min_length=8,max_length=240)
    mechanisms: list[Literal['knowledge_depth','reasoning_steps','method_combination','parameter_structure','application']] = Field(default_factory=list,max_length=5)
