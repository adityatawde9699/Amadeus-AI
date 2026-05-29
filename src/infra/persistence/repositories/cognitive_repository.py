"""Repository for durable cognitive runtime execution state."""

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.persistence.orm_models import (
    CognitiveObservationORM,
    CognitivePlanORM,
    CognitivePlanStatusDB,
    CognitivePlanStepORM,
    CognitiveReflectionORM,
    CognitiveStepStatusDB,
)
from src.runtime.cognitive.models import (
    Observation,
    Plan,
    PlanStatus,
    PlanStep,
    Reflection,
    StepStatus,
)


class SQLAlchemyCognitiveRepository:
    """SQLAlchemy implementation for cognitive plans, steps, and observations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_plan(self, plan: Plan) -> Plan:
        orm = CognitivePlanORM(
            id=plan.id,
            request_id=plan.request_id or "",
            session_id=plan.session_id or "",
            user_id=plan.user_id or "",
            goal_id=plan.goal_id,
            original_task=plan.original_task,
            status=CognitivePlanStatusDB(plan.status.value),
            version=plan.version,
        )
        self._session.add(orm)
        await self._session.flush()
        for step in plan.steps:
            await self.add_step(plan.id, step)
        return plan

    async def update_plan_status(
        self,
        plan_id: str,
        status: PlanStatus,
        final_output: str | None = None,
        error_message: str | None = None,
    ) -> None:
        orm = await self._session.get(CognitivePlanORM, plan_id)
        if not orm:
            return
        orm.status = CognitivePlanStatusDB(status.value)
        orm.final_output = final_output
        orm.error_message = error_message
        await self._session.flush()

    async def add_step(self, plan_id: str, step: PlanStep) -> PlanStep:
        orm = CognitivePlanStepORM(
            id=step.id,
            plan_id=plan_id,
            name=step.name,
            description=step.description,
            tool=step.tool,
            args=step.args,
            status=CognitiveStepStatusDB(step.status.value),
            dependencies=step.dependencies,
            risk_level=step.risk_level,
            max_retries=step.max_retries,
            retry_count=step.retry_count,
            started_at=step.started_at,
            completed_at=step.completed_at,
        )
        self._session.add(orm)
        await self._session.flush()
        return step

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        orm = await self._session.get(CognitivePlanStepORM, step.id)
        if not orm:
            await self.add_step(plan_id, step)
            return
        orm.status = CognitiveStepStatusDB(step.status.value)
        orm.retry_count = step.retry_count
        orm.started_at = step.started_at
        orm.completed_at = step.completed_at
        orm.args = step.args
        await self._session.flush()

    async def add_observation(
        self,
        plan_id: str,
        step_id: str | None,
        observation: Observation,
    ) -> Observation:
        created_at = observation.timestamp
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(UTC).replace(tzinfo=None)
        orm = CognitiveObservationORM(
            id=observation.id,
            plan_id=plan_id,
            step_id=step_id,
            source=observation.source,
            content=observation.content,
            success=observation.success,
            observation_metadata=observation.metadata,
            created_at=created_at,
        )
        self._session.add(orm)
        await self._session.flush()
        return observation

    async def add_reflection(
        self,
        plan_id: str,
        step_id: str | None,
        reflection: Reflection,
    ) -> Reflection:
        created_at = reflection.timestamp
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(UTC).replace(tzinfo=None)
        orm = CognitiveReflectionORM(
            id=reflection.id,
            plan_id=plan_id,
            step_id=step_id,
            confidence=reflection.confidence,
            analysis=reflection.analysis,
            suggested_action=reflection.suggested_action,
            is_dead_end=reflection.is_dead_end,
            created_at=created_at,
        )
        self._session.add(orm)
        await self._session.flush()
        return reflection

    async def get_plan(self, plan_id: str) -> Plan | None:
        plan_orm = await self._session.get(CognitivePlanORM, plan_id)
        if not plan_orm:
            return None

        result = await self._session.execute(
            select(CognitivePlanStepORM)
            .where(CognitivePlanStepORM.plan_id == plan_id)
            .order_by(CognitivePlanStepORM.created_at.asc())
        )
        steps = [
            PlanStep(
                id=step.id,
                name=step.name,
                description=step.description,
                tool=step.tool,
                args=step.args or {},
                status=StepStatus(step.status.value),
                dependencies=list(step.dependencies or []),
                risk_level=step.risk_level,
                max_retries=step.max_retries,
                retry_count=step.retry_count,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            for step in result.scalars().all()
        ]
        return Plan(
            id=plan_orm.id,
            request_id=plan_orm.request_id,
            session_id=plan_orm.session_id,
            user_id=plan_orm.user_id,
            goal_id=plan_orm.goal_id,
            original_task=plan_orm.original_task,
            status=PlanStatus(plan_orm.status.value),
            version=plan_orm.version,
            steps=steps,
            created_at=plan_orm.created_at,
            updated_at=plan_orm.updated_at or plan_orm.created_at,
        )
