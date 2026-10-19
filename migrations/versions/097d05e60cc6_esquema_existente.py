"""Esquema inicial

Revision ID: 097d05e60cc6
Revises: 
Create Date: 2026-10-06 21:02:44.168339

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '097d05e60cc6'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cursos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('descripcion', sa.String(length=300), nullable=True),
        sa.Column('precio', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('inscripciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('curso_id', sa.Integer(), nullable=False),
        sa.Column('alumno_nombre', sa.String(length=120), nullable=False),
        sa.Column('monto', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='pendiente'),
        sa.ForeignKeyConstraint(['curso_id'], ['cursos.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('pagos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inscripcion_id', sa.Integer(), nullable=False),
        sa.Column('proveedor', sa.String(length=30), nullable=False, server_default='mercado_pago'),
        sa.Column('preferencia_id', sa.String(length=100), nullable=True),
        sa.Column('pago_externo_id', sa.String(length=100), nullable=True),
        sa.Column('monto', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('moneda', sa.String(length=3), nullable=False, server_default='ARS'),
        sa.Column('estado', sa.String(length=30), nullable=False, server_default='pendiente'),
        sa.ForeignKeyConstraint(['inscripcion_id'], ['inscripciones.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('pagos')
    op.drop_table('inscripciones')
    op.drop_table('cursos')