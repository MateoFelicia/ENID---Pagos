"""Noticias y suscriptores del newsletter

Revision ID: b4d8f2a6c1e3
Revises: a7c3e9f1b5d2
Create Date: 2026-11-26 04:14:51.693801

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4d8f2a6c1e3'
down_revision = 'a7c3e9f1b5d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('suscriptores',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('confirmado', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('creado_en', sa.DateTime(), nullable=True),
    sa.Column('confirmado_en', sa.DateTime(), nullable=True),
    sa.Column('baja_en', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('noticias',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=160), nullable=False),
    sa.Column('resumen', sa.String(length=300), nullable=True),
    sa.Column('cuerpo', sa.Text(), nullable=False),
    sa.Column('imagen_id', sa.Integer(), nullable=True),
    sa.Column('publicada', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('publicada_en', sa.DateTime(), nullable=True),
    sa.Column('creada_en', sa.DateTime(), nullable=True),
    sa.Column('enviada_en', sa.DateTime(), nullable=True),
    sa.Column('enviada_a', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['imagen_id'], ['imagenes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('noticias')
    op.drop_table('suscriptores')
