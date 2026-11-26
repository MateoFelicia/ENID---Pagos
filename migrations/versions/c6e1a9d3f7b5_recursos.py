"""Podcasts y biblioteca

Revision ID: c6e1a9d3f7b5
Revises: b4d8f2a6c1e3
Create Date: 2026-11-26 04:18:58.610195

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6e1a9d3f7b5'
down_revision = 'b4d8f2a6c1e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('episodios',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=160), nullable=False),
    sa.Column('descripcion', sa.String(length=1000), nullable=True),
    sa.Column('url', sa.String(length=300), nullable=False),
    sa.Column('duracion_min', sa.Integer(), nullable=True),
    sa.Column('fecha', sa.Date(), nullable=True),
    sa.Column('visible', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('libros',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=160), nullable=False),
    sa.Column('autor', sa.String(length=160), nullable=True),
    sa.Column('tema', sa.String(length=60), nullable=True),
    sa.Column('descripcion', sa.String(length=600), nullable=True),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('imagen_id', sa.Integer(), nullable=True),
    sa.Column('orden', sa.Integer(), server_default='1', nullable=False),
    sa.Column('visible', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.ForeignKeyConstraint(['imagen_id'], ['imagenes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('libros')
    op.drop_table('episodios')
