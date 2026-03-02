"""Serviço de gerenciamento de Skills."""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import BASE_DIR
from app.core.exceptions import NotFoundError
from app.models.skill import Skill, SkillExample, SkillStep
from app.schemas.skill import SkillCreate, SkillUpdate, StepCreate, StepSyncItem, StepUpdate

logger = logging.getLogger(__name__)

EXAMPLES_DIR = BASE_DIR / "data" / "examples"


class SkillService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Skill]:
        result = await self.db.execute(select(Skill).order_by(Skill.name))
        return result.scalars().all()

    async def get_by_id(self, skill_id: int) -> Skill:
        skill = await self.db.get(Skill, skill_id)
        if not skill:
            raise NotFoundError(404, f"Skill {skill_id} não encontrada")
        # Carrega relacionamentos
        await self.db.refresh(skill, ["steps", "examples"])
        return skill

    async def create(self, data: SkillCreate) -> Skill:
        skill = Skill(**data.model_dump())
        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill, ["steps", "examples"])
        return skill

    async def update(self, skill_id: int, data: SkillUpdate) -> Skill:
        skill = await self.get_by_id(skill_id)
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(skill, key, value)
        skill.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(skill, ["steps", "examples"])
        return skill

    async def delete(self, skill_id: int) -> None:
        skill = await self.get_by_id(skill_id)
        # Remove arquivos de exemplo do disco
        example_dir = EXAMPLES_DIR / str(skill_id)
        if example_dir.exists():
            import shutil
            shutil.rmtree(example_dir)
        await self.db.delete(skill)
        await self.db.commit()

    # --- Steps ---

    async def add_step(self, skill_id: int, data: StepCreate) -> SkillStep:
        await self.get_by_id(skill_id)  # valida existência
        # Calcula próximo order
        result = await self.db.execute(
            select(SkillStep).where(SkillStep.skill_id == skill_id).order_by(SkillStep.order.desc())
        )
        last = result.scalars().first()
        next_order = (last.order + 1) if last else 1

        step = SkillStep(skill_id=skill_id, order=next_order, **data.model_dump())
        self.db.add(step)
        await self.db.commit()
        await self.db.refresh(step)
        return step

    async def update_step(self, skill_id: int, step_id: int, data: StepUpdate) -> SkillStep:
        step = await self.db.get(SkillStep, step_id)
        if not step or step.skill_id != skill_id:
            raise NotFoundError(404, f"Step {step_id} não encontrada")
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(step, key, value)
        await self.db.commit()
        await self.db.refresh(step)
        return step

    async def delete_step(self, skill_id: int, step_id: int) -> None:
        step = await self.db.get(SkillStep, step_id)
        if not step or step.skill_id != skill_id:
            raise NotFoundError(404, f"Step {step_id} não encontrada")
        await self.db.delete(step)
        await self.db.commit()

    async def sync_steps(self, skill_id: int, items: list[StepSyncItem]) -> list[SkillStep]:
        """Substitui todas as etapas de uma skill atomicamente numa única transação."""
        skill = await self.get_by_id(skill_id)

        # Remove etapas existentes
        existing = await self.db.execute(
            select(SkillStep).where(SkillStep.skill_id == skill_id)
        )
        for step in existing.scalars().all():
            await self.db.delete(step)

        # Cria novas etapas
        new_steps = []
        for order, item in enumerate(items, start=1):
            if not item.title.strip():
                continue
            step = SkillStep(
                skill_id=skill_id,
                order=order,
                title=item.title,
                instruction=item.instruction,
                expected_output=item.expected_output,
            )
            self.db.add(step)
            new_steps.append(step)

        skill.updated_at = datetime.now(timezone.utc)

        # Commit único — se falhar, nada é alterado
        await self.db.commit()

        for step in new_steps:
            await self.db.refresh(step)
        return new_steps

    # --- Examples ---

    async def add_example(
        self, skill_id: int, file: UploadFile, description: str
    ) -> SkillExample:
        await self.get_by_id(skill_id)
        # Salva arquivo em disco
        example_dir = EXAMPLES_DIR / str(skill_id)
        example_dir.mkdir(parents=True, exist_ok=True)
        file_path = example_dir / file.filename
        content = await file.read()
        file_path.write_bytes(content)

        example = SkillExample(
            skill_id=skill_id,
            filename=file.filename,
            file_path=str(file_path),
            description=description,
            mime_type=file.content_type or "application/octet-stream",
        )
        self.db.add(example)
        await self.db.commit()
        await self.db.refresh(example)
        return example

    async def delete_example(self, skill_id: int, example_id: int) -> None:
        example = await self.db.get(SkillExample, example_id)
        if not example or example.skill_id != skill_id:
            raise NotFoundError(404, f"Example {example_id} não encontrado")
        # Remove arquivo do disco
        try:
            os.remove(example.file_path)
        except FileNotFoundError:
            pass
        await self.db.delete(example)
        await self.db.commit()

    # --- Prompt Builder ---

    async def build_prompt(self, skill_id: int) -> str:
        """Monta o prompt completo da skill para o Gemini."""
        skill = await self.get_by_id(skill_id)

        # Injeta data atual para o modelo não alucinar datas
        meses = [
            "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        ]
        hoje = datetime.now()
        data_str = f"{hoje.day} de {meses[hoje.month]} de {hoje.year}"
        parts = [
            f"Data atual: {data_str}. Use esta data como 'Data da conferência' quando solicitado.\n",
            skill.macro_instruction,
        ]

        if skill.steps:
            parts.append("\n## Etapas de Análise\n")
            for step in sorted(skill.steps, key=lambda s: s.order):
                parts.append(f"### Etapa {step.order}: {step.title}")
                parts.append(step.instruction)
                if step.expected_output:
                    parts.append(f"**Output esperado:** {step.expected_output}")
                parts.append("")

        if skill.examples:
            parts.append("\n## Arquivos de Referência\n")
            for ex in skill.examples:
                parts.append(f"- **{ex.filename}**: {ex.description}")

        return "\n".join(parts)
