from alembic import context

def run_migrations():
    connection = context.config.attributes['connection']
    context.configure(connection=connection, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()

run_migrations()
