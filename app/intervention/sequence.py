"""Deterministic stages for a brief protection intervention."""

from __future__ import annotations

from dataclasses import dataclass

from app import config


@dataclass(frozen=True, slots=True)
class InterventionStep:
    """Content and timing for one intervention stage."""

    name: str
    title: str
    body: str
    button_label: str
    duration_seconds: float | None
    can_dismiss: bool = False


class InterventionSequence:
    """Move forward through intervention stages without skipping."""

    def __init__(self, steps: tuple[InterventionStep, ...]) -> None:
        if not steps:
            raise ValueError("intervention sequence requires at least one step")
        if any(step.duration_seconds is None for step in steps[:-1]):
            raise ValueError("only the final intervention step may have no duration")
        if any(
            step.duration_seconds is not None and step.duration_seconds <= 0
            for step in steps
        ):
            raise ValueError("intervention durations must be positive")
        if steps[-1].duration_seconds is not None:
            raise ValueError("the final intervention step must wait for the user")
        if any(step.can_dismiss for step in steps[:-1]):
            raise ValueError("only the final intervention step may be dismissed")
        if not steps[-1].can_dismiss:
            raise ValueError("the final intervention step must be dismissible")

        self._steps = steps
        self._index = 0

    @property
    def current(self) -> InterventionStep:
        return self._steps[self._index]

    @property
    def can_dismiss(self) -> bool:
        return self.current.can_dismiss

    def advance(self) -> bool:
        """Advance once and report whether the stage changed."""

        if self._index >= len(self._steps) - 1:
            return False
        self._index += 1
        return True


def default_intervention_sequence(language: str = "en") -> InterventionSequence:
    """Build the product's default pause, breathing, and ready stages."""

    chinese = language == "zh"
    return InterventionSequence(
        (
            InterventionStep(
                name="pause",
                title=("先停下来一会儿" if chinese else config.OVERLAY_PAUSE_TITLE),
                body=("把视线从触发内容上移开，给冲动一点消退的时间。" if chinese else config.OVERLAY_PAUSE_BODY),
                button_label=("陪自己停留片刻" if chinese else config.OVERLAY_WAIT_BUTTON_LABEL),
                duration_seconds=config.INTERVENTION_PAUSE_SECONDS,
            ),
            InterventionStep(
                name="breathe",
                title=("慢慢做一次深呼吸" if chinese else config.OVERLAY_BREATHE_TITLE),
                body=("轻轻吸气，再更缓慢地呼气。" if chinese else config.OVERLAY_BREATHE_BODY),
                button_label=("陪自己停留片刻" if chinese else config.OVERLAY_WAIT_BUTTON_LABEL),
                duration_seconds=config.INTERVENTION_BREATHE_SECONDS,
            ),
            InterventionStep(
                name="ready",
                title=("选择接下来要做的事" if chinese else config.OVERLAY_READY_TITLE),
                body=("你仍然掌握着主动权。关掉触发内容的页面，站起身，朝真正重要的事迈出一小步。" if chinese else config.OVERLAY_READY_BODY),
                button_label=("我准备好继续了" if chinese else config.OVERLAY_READY_BUTTON_LABEL),
                duration_seconds=None,
                can_dismiss=True,
            ),
        )
    )
