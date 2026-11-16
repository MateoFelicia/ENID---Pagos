"""Agregar clases (varias por curso)

Revision ID: c4d2a9f1b7e3
Revises: 961fbd7fbad0
Create Date: 2026-10-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d2a9f1b7e3'
down_revision = '961fbd7fbad0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('curso_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sa.String(length=160), nullable=False),
        sa.Column('descripcion', sa.String(length=500), nullable=True),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('fecha', sa.DateTime(), nullable=True),
        sa.Column('meet_link', sa.String(length=300), nullable=True),
        sa.Column('grabacion', sa.String(length=300), nullable=True),
        sa.Column('publicada', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['curso_id'], ['cursos.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Los cursos que ya tenían fecha / Meet / grabación pasan a ser su "Clase 1".
    # Las columnas viejas de "cursos" no se borran (migración sin pérdida de datos).
    conexion = op.get_bind()
    cursos = conexion.execute(sa.text(
        "SELECT id, fecha, meet_link, grabacion FROM cursos "
        "WHERE fecha IS NOT NULL OR meet_link IS NOT NULL OR grabacion IS NOT NULL"
    )).fetchall()
    for curso_id, fecha, meet_link, grabacion in cursos:
        conexion.execute(
            sa.text(
                "INSERT INTO clases (curso_id, titulo, orden, fecha, meet_link, grabacion, publicada) "
                "VALUES (:curso_id, 'Clase 1', 1, :fecha, :meet_link, :grabacion, :publicada)"
            ),
            {"curso_id": curso_id, "fecha": fecha, "meet_link": meet_link,
             "grabacion": grabacion, "publicada": True},
        )


def downgrade():
    op.drop_table('clases')
