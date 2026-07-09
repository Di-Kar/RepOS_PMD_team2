import uuid
from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from src.models.entity import User, Role, UserRole, LoginHistory


class TestPostgresConnection:
    """Тесты подключения к PostgreSQL"""
    
    async def test_connection(self, db_session: AsyncSession):
        """Проверяем, что подключение к БД работает"""
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    
    async def test_database_tables_exist(self, db_session: AsyncSession):
        """Проверяем, что все таблицы созданы"""
        result = await db_session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
        )
        tables = [row[0] for row in result.fetchall()]
        
        assert "users" in tables
        assert "roles" in tables
        assert "user_roles" in tables
        assert "login_history" in tables


class TestUserModel:
    """Тесты модели User"""
    
    async def test_create_user(self, db_session: AsyncSession):
        """Создание пользователя"""
        user = User(
            login="john_doe",
            password="hashed_password",
            first_name="John",
            last_name="Doe",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        assert user.id is not None
        assert user.login == "john_doe"
        assert user.first_name == "John"
        assert user.is_active is True
        assert user.is_superuser is False
        assert isinstance(user.created_at, datetime)
    
    async def test_unique_login_constraint(self, db_session: AsyncSession):
        """Проверяем уникальность логина"""
        user1 = User(login="unique_login", password="pass1")
        user2 = User(login="unique_login", password="pass2")
        
        db_session.add(user1)
        await db_session.commit()
        
        db_session.add(user2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_read_user(self, db_session: AsyncSession, sample_user: User):
        """Чтение пользователя из БД"""
        result = await db_session.execute(
            select(User).where(User.id == sample_user.id)
        )
        user = result.scalar_one()
        
        assert user.login == sample_user.login
        assert user.first_name == sample_user.first_name
    
    async def test_update_user(self, db_session: AsyncSession, sample_user: User):
        """Обновление пользователя"""
        sample_user.first_name = "Updated"
        sample_user.is_active = False
        await db_session.commit()
        await db_session.refresh(sample_user)
        
        assert sample_user.first_name == "Updated"
        assert sample_user.is_active is False
        assert isinstance(sample_user.updated_at, datetime)
    
    async def test_delete_user(self, db_session: AsyncSession, sample_user: User):
        """Удаление пользователя"""
        user_id = sample_user.id
        await db_session.delete(sample_user)
        await db_session.commit()
        
        result = await db_session.execute(select(User).where(User.id == user_id))
        assert result.scalar_one_or_none() is None


class TestRoleModel:
    """Тесты модели Role"""
    
    async def test_create_role(self, db_session: AsyncSession):
        """Создание роли"""
        role = Role(
            name="admin",
            description="Administrator role",
        )
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)
        
        assert role.id is not None
        assert role.name == "admin"
        assert role.description == "Administrator role"
    
    async def test_unique_role_name(self, db_session: AsyncSession):
        """Уникальность имени роли"""
        role1 = Role(name="moderator")
        role2 = Role(name="moderator")
        
        db_session.add(role1)
        await db_session.commit()
        
        db_session.add(role2)
        with pytest.raises(IntegrityError):
            await db_session.commit()



############################################
class TestUserRoleRelation:
    """Тесты связи User-Role (Many-to-Many)"""
    
    async def test_assign_role_to_user(
        self, 
        db_session: AsyncSession,
        sample_user: User,
        sample_role: Role,
    ):
        """Назначение роли пользователю"""
        # Сохраняем ID ДО expire_all, чтобы не было ленивой загрузки
        user_id = sample_user.id
        role_id = sample_role.id
        
        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
        )
        db_session.add(user_role)
        await db_session.commit()
        
        # Сбрасываем кэш сессии
        db_session.expire_all()
        
        # Используем сохранённые ID, а не sample_user.id
        result = await db_session.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.user_roles))
        )
        user = result.unique().scalar_one()
        
        assert len(user.user_roles) == 1
        assert user.user_roles[0].role_id == role_id
    
    async def test_user_can_have_multiple_roles(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Пользователь может иметь несколько ролей"""
        # Сохраняем ID ДО expire_all
        user_id = sample_user.id
        
        role1 = Role(name="role1")
        role2 = Role(name="role2")
        db_session.add_all([role1, role2])
        await db_session.commit()
        
        db_session.add_all([
            UserRole(user_id=user_id, role_id=role1.id),
            UserRole(user_id=user_id, role_id=role2.id),
        ])
        await db_session.commit()
        
        # Сохраняем ID ролей
        role1_id = role1.id
        role2_id = role2.id
        
        # Сбрасываем кэш сессии
        db_session.expire_all()
        
        # Используем сохранённый user_id
        result = await db_session.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.user_roles))
        )
        user = result.unique().scalar_one()
        
        assert len(user.user_roles) == 2
        role_ids = {ur.role_id for ur in user.user_roles}
        assert role1_id in role_ids
        assert role2_id in role_ids
    
    async def test_unique_user_role_constraint(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_role: Role,
    ):
        """Нельзя назначить одну и ту же роль дважды"""
        user_role1 = UserRole(user_id=sample_user.id, role_id=sample_role.id)
        user_role2 = UserRole(user_id=sample_user.id, role_id=sample_role.id)
        
        db_session.add(user_role1)
        await db_session.commit()
        
        db_session.add(user_role2)
        with pytest.raises(IntegrityError):
            await db_session.commit()


#################################################

class TestLoginHistory:
    """Тесты истории входов"""
    
    async def test_create_login_history(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """Создание записи истории входа"""
        history = LoginHistory(
            user_id=sample_user.id,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            ip_address="192.168.1.1",
            fingerprint="abc123def456",
            success=True,
        )
        db_session.add(history)
        await db_session.commit()
        await db_session.refresh(history)
        
        assert history.id is not None
        assert history.user_id == sample_user.id
        assert history.ip_address == "192.168.1.1"
        assert history.success is True
    
    async def test_cascade_delete_on_user_delete(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        """При удалении пользователя удаляется его история"""
        history = LoginHistory(
            user_id=sample_user.id,
            user_agent="Test Agent",
            success=True,
        )
        db_session.add(history)
        await db_session.commit()
        history_id = history.id
        
        await db_session.delete(sample_user)
        await db_session.commit()
        
        result = await db_session.execute(
            select(LoginHistory).where(LoginHistory.id == history_id)
        )
        assert result.scalar_one_or_none() is None
