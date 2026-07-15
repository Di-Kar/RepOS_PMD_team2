"""Консольные команды управления сервисом.

Создание суперпользователя:
    python -m src.cli create-superuser admin@example.com --password 'Secret123!' --full-name 'Super Admin'
"""
import asyncio
from typing import Optional

import typer
from sqlalchemy import select

from src.core.security import hash_password
from src.db.postgres import AsyncSessionLocal, engine
from src.models.entity import User
from src.services.auth_service import split_full_name

cli = typer.Typer(help="Команды управления auth_service")


async def _create_superuser(email: str, password: str, full_name: Optional[str]) -> str:
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
            first_name, last_name = split_full_name(full_name)
            session.add(
                User(
                    login=email,
                    password=hash_password(password),
                    first_name=first_name,
                    last_name=last_name,
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
    full_name: Optional[str] = typer.Option(None, "--full-name", help="ФИО"),
) -> None:
    """Создаёт суперпользователя (или повышает существующего пользователя)."""
    if len(password) < 8:
        typer.secho("Пароль должен быть не короче 8 символов", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    message = asyncio.run(_create_superuser(email, password, full_name))
    typer.secho(message, fg=typer.colors.GREEN)


if __name__ == "__main__":
    cli()
