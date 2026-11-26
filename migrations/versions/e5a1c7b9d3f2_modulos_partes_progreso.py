"""Módulos, partes de video y progreso de los alumnos

Revision ID: e5a1c7b9d3f2
Revises: d7f1b3a9c5e2
Create Date: 2026-11-25 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5a1c7b9d3f2'
down_revision = 'd7f1b3a9c5e2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'modulos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('curso_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sa.String(length=160), nullable=False),
        sa.Column('descripcion', sa.String(length=500), nullable=True),
        sa.Column('orden', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['curso_id'], ['cursos.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # batch_alter_table para que también funcione en SQLite
    with op.batch_alter_table('clases') as batch_op:
        batch_op.add_column(sa.Column('modulo_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_clases_modulo_id', 'modulos', ['modulo_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'partes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clase_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sa.String(length=160), nullable=False),
        sa.Column('video_url', sa.String(length=300), nullable=True),
        sa.Column('duracion_min', sa.Integer(), nullable=True),
        sa.Column('orden', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['clase_id'], ['clases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'progresos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('clase_id', sa.Integer(), nullable=False),
        sa.Column('parte_id', sa.Integer(), nullable=True),
        sa.Column('completado_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clase_id'], ['clases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parte_id'], ['partes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('usuario_id', 'clase_id', 'parte_id', name='uq_progreso'),
    )


def downgrade():
    op.drop_table('progresos')
    op.drop_table('partes')
    with op.batch_alter_table('clases') as batch_op:
        batch_op.drop_constraint('fk_clases_modulo_id', type_='foreignkey')
        batch_op.drop_column('modulo_id')
    op.drop_table('modulos')
