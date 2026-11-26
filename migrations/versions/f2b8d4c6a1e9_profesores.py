"""Rol de profesor, perfil público y profes de cada curso

Revision ID: f2b8d4c6a1e9
Revises: e5a1c7b9d3f2
Create Date: 2026-11-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b8d4c6a1e9'
down_revision = 'e5a1c7b9d3f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.add_column(sa.Column('es_profesor', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('titulo_profesional', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('bio', sa.String(length=1500), nullable=True))
        batch_op.add_column(sa.Column('foto_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_usuarios_foto_id', 'imagenes', ['foto_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'curso_profesores',
        sa.Column('curso_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['curso_id'], ['cursos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('curso_id', 'usuario_id'),
    )


def downgrade():
    op.drop_table('curso_profesores')
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.drop_constraint('fk_usuarios_foto_id', type_='foreignkey')
        batch_op.drop_column('foto_id')
        batch_op.drop_column('bio')
        batch_op.drop_column('titulo_profesional')
        batch_op.drop_column('es_profesor')
