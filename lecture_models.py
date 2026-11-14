"""Video-grounded classroom analysis; time coverage is not a correctness certificate."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Nonblank = Annotated[str, Field(min_length=1, max_length=2400)]


class LectureItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    kind: Literal["introduction", "definition", "theorem", "proof", "example", "exercise", "discussion", "other"]
    title: str = Field(min_length=1, max_length=180)
    evidence: Literal["audio", "visual", "audio_visual", "unclear"]
    source_summary: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=6000)
    formulas: list[Nonblank] = Field(max_length=12)
    steps: list[Nonblank] = Field(max_length=24)
    uncertainties: list[Nonblank] = Field(max_length=12)

    @model_validator(mode="after")
    def valid_item(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("课堂内容的结束时间必须晚于开始时间")
        if any(not text.strip() for text in [self.title, self.source_summary, self.explanation,
                                             *self.formulas, *self.steps, *self.uncertainties]):
            raise ValueError("课堂解析内容不能为空白")
        return self


class LecturePractice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: Nonblank
    hint: Nonblank
    answer: str = Field(min_length=1, max_length=4000)
    origin: Literal["from_video", "supplement"]

    @model_validator(mode="after")
    def nonblank(self):
        if not all(value.strip() for value in [self.question, self.hint, self.answer]):
            raise ValueError("练习和参考答案不能为空白")
        return self


class ClipAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=180)
    overview: str = Field(min_length=1, max_length=4000)
    items: list[LectureItem] = Field(min_length=1, max_length=60)
    learning_goals: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(max_length=16)
    practice: list[LecturePractice] = Field(max_length=6)
    coverage_notes: list[Nonblank] = Field(max_length=20)
    uncertainties: list[Nonblank] = Field(max_length=20)

    @model_validator(mode="after")
    def nonblank(self):
        if any(not text.strip() for text in [self.title, self.overview, *self.learning_goals,
                                             *self.coverage_notes, *self.uncertainties]):
            raise ValueError("解析标题、概述与说明不能为空白")
        if any(left.start_seconds > right.start_seconds for left, right in zip(self.items, self.items[1:])):
            raise ValueError("课堂内容必须按视频时间顺序排列")
        return self


def validate_clip(value: dict, start: float, end: float) -> ClipAnalysis:
    result = ClipAnalysis.model_validate(value)
    if any(item.start_seconds < start or item.end_seconds > end for item in result.items):
        raise ValueError("解析引用了本段视频之外的时间")
    return result
