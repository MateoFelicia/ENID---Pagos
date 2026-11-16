"""Datos del alumno, contenido del sitio, avisos por mail y arrepentimiento

Revision ID: d7f1b3a9c5e2
Revises: c4d2a9f1b7e3
Create Date: 2026-10-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7f1b3a9c5e2'
down_revision = 'c4d2a9f1b7e3'
branch_labels = None
depends_on = None


def upgrade():
    # --- Datos del alumno (las filas existentes quedan en NULL: se muestran como "—")
    op.add_column('usuarios', sa.Column('creado_en', sa.DateTime(), nullable=True))
    op.add_column('usuarios', sa.Column('ultimo_ingreso', sa.DateTime(), nullable=True))
    op.add_column('usuarios', sa.Column('avisos_email', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('inscripciones', sa.Column('creado_en', sa.DateTime(), nullable=True))
    op.add_column('inscripciones', sa.Column('pagado_en', sa.DateTime(), nullable=True))
    op.add_column('inscripciones', sa.Column('medio', sa.String(length=30), nullable=True))
    op.add_column('inscripciones', sa.Column('nota', sa.String(length=200), nullable=True))

    # --- Contenido del sitio
    op.create_table(
        'imagenes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=160), nullable=True),
        sa.Column('mimetype', sa.String(length=40), nullable=False),
        sa.Column('datos', sa.LargeBinary(), nullable=False),
        sa.Column('ancho', sa.Integer(), nullable=True),
        sa.Column('alto', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'fotos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('imagen_id', sa.Integer(), nullable=False),
        sa.Column('pie', sa.String(length=160), nullable=True),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('visible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['imagen_id'], ['imagenes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'testimonios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('detalle', sa.String(length=160), nullable=True),
        sa.Column('texto', sa.String(length=800), nullable=False),
        sa.Column('imagen_id', sa.Integer(), nullable=True),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('visible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['imagen_id'], ['imagenes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'preguntas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pregunta', sa.String(length=200), nullable=False),
        sa.Column('respuesta', sa.String(length=1200), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('visible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'ajustes',
        sa.Column('clave', sa.String(length=60), nullable=False),
        sa.Column('valor', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('clave'),
    )

    # --- Avisos por mail y arrepentimiento
    op.create_table(
        'envios_aviso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clase_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('enviado_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['clase_id'], ['clases.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clase_id', 'usuario_id', 'tipo', name='uq_envio_aviso'),
    )
    op.create_table(
        'arrepentimientos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(length=12), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('referencia', sa.String(length=200), nullable=True),
        sa.Column('motivo', sa.String(length=1000), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='recibida'),
        sa.Column('creado_en', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('codigo'),
    )


def downgrade():
    op.drop_table('arrepentimientos')
    op.drop_table('envios_aviso')
    op.drop_table('ajustes')
    op.drop_table('preguntas')
    op.drop_table('testimonios')
    op.drop_table('fotos')
    op.drop_table('imagenes')
    with op.batch_alter_table('inscripciones') as lote:
        lote.drop_column('nota')
        lote.drop_column('medio')
        lote.drop_column('pagado_en')
        lote.drop_column('creado_en')
    with op.batch_alter_table('usuarios') as lote:
        lote.drop_column('avisos_email')
        lote.drop_column('ultimo_ingreso')
        lote.drop_column('creado_en')
