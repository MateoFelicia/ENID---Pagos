from app import app, db
from models import Curso

with app.app_context():
    for nombre, precio in [('Curso Basico', 5000), ('Curso Avanzado', 8000), ('Curso Pro', 12000)]:
        if not Curso.query.filter_by(nombre=nombre).first():
            c = Curso(nombre=nombre, descripcion='Descripcion de ' + nombre, precio=precio, activo=True)
            db.session.add(c)
    db.session.commit()
    print('Cursos de prueba creados')
    for c in Curso.query.all():
        print(f'  {c.id}: {c.nombre} - ${c.precio}')