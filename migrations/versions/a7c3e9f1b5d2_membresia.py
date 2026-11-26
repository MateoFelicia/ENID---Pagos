"""Membresía mensual: plan y suscripciones (preapproval de Mercado Pago)

Revision ID: a7c3e9f1b5d2
Revises: f2b8d4c6a1e9
Create Date: 2026-11-26 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e9f1b5d2'
down_revision = 'f2b8d4c6a1e9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'planes_membresia',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('descripcion', sa.String(length=500), nullable=True),
        sa.Column('precio', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('activo', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'suscripciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('monto', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('mp_preapproval_id', sa.String(length=80), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=True),
        sa.Column('actualizado_en', sa.DateTime(), nullable=True),
        sa.Column('proximo_cobro', sa.DateTime(), nullable=True),
        sa.Column('acceso_hasta', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['planes_membresia.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mp_preapproval_id'),
    )


def downgrade():
    op.drop_table('suscripciones')
    op.drop_table('planes_membresia')
