"""Консольные команды управления сервисом.

Создание суперпользователя:
    python -m src.cli create-superuser admin@example.com --password 'Secret123!'

Создание роли IDM с правами:
    python -m src.cli create-role profiles_viewer --permission profiles:view
"""

import asyncio
from typing import List, Optional

import typer
from sqlalchemy import select

from src.core.exceptions import RoleAlreadyExistsError
from src.core.security import hash_password
from src.db.postgres import AsyncSessionLocal, engine
from src.models.entity import User
from src.services.role_service import RoleService

cli = typer.Typer(help="Команды управления auth_service")


@cli.callback()
def _main() -> None:
    """Обязателен: без callback Typer с одной командой не требует её имени."""


async def _create_superuser(email: str, password: str) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.login == email))
        user = result.scalar_one_or_none()

        if user is not None:
            # Существующего пользователя повышаем до суперпользователя и обновляем пароль.
            user.is_superuser = True
            user.is_active = True
            user.password = hash_password(password)
            message = f"Пользователь {email} повышен до суперпользователя"
        else:
            session.add(
                User(
                    login=email,
                    password=hash_password(password),
                    is_superuser=True,
                )
            )
            message = f"Суперпользователь {email} создан"

        await session.commit()
    await engine.dispose()
    return message


@cli.command("create-superuser")
def create_superuser(
    email: str = typer.Argument(..., help="Email (логин) суперпользователя"),
    password: str = typer.Option(
        ..., "--password", "-p", prompt=True, hide_input=True, help="Пароль"
    ),
    # Параметр full_name удалён, так как auth_service больше не хранит ФИО
) -> None:
    """Создаёт суперпользователя (или повышает существующего пользователя)."""
    if len(password) < 8:
        typer.secho("Пароль должен быть не короче 8 символов", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    message = asyncio.run(_create_superuser(email, password))
    typer.secho(message, fg=typer.colors.GREEN)


async def _create_role(name: str, description: Optional[str], permissions: List[str]) -> str:
    async with AsyncSessionLocal() as session:
        try:
            await RoleService(session).create(name, description, permissions)
        except RoleAlreadyExistsError:
            # Повторный запуск не должен падать: роль уже на месте.
            message = f"Роль {name} уже существует"
        else:
            message = f"Роль {name} создана, права: {', '.join(permissions)}"
    await engine.dispose()
    return message


@cli.command("create-role")
def create_role(
    name: str = typer.Argument(..., help="Имя роли, например profiles_viewer"),
    permission: List[str] = typer.Option(
        ..., "--permission", "-p", help="Право (можно несколько раз), например profiles:view"
    ),
    description: Optional[str] = typer.Option(None, "--description", help="Описание роли"),
) -> None:
    """Создаёт роль IDM с перечисленными правами (идемпотентно по имени)."""
    message = asyncio.run(_create_role(name, description, permission))
    typer.secho(message, fg=typer.colors.GREEN)


if __name__ == "__main__":
    cli()