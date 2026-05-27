"""remove_kg_tables

Revision ID: 52a12a970e5b
Revises: 8b924c237530
Create Date: 2026-05-27 10:38:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '52a12a970e5b'
down_revision = '8b924c237530'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Drop indexes first
    op.drop_index('idx_entity_name_type', table_name='graph_entities')
    op.drop_index('idx_rel_predicate', table_name='graph_relationships')
    op.drop_index('idx_rel_triple', table_name='graph_relationships')
    op.drop_index(op.f('ix_graph_relationships_object_id'), table_name='graph_relationships')
    op.drop_index(op.f('ix_graph_relationships_predicate'), table_name='graph_relationships')
    op.drop_index(op.f('ix_graph_relationships_subject_id'), table_name='graph_relationships')
    op.drop_index(op.f('ix_graph_entities_entity_type'), table_name='graph_entities')
    op.drop_index(op.f('ix_graph_entities_name'), table_name='graph_entities')
    
    # Drop tables
    op.drop_table('graph_relationships')
    op.drop_table('graph_entities')

def downgrade() -> None:
    # Recreate graph_entities
    op.create_table('graph_entities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_graph_entities_name'), 'graph_entities', ['name'], unique=False)
    op.create_index(op.f('ix_graph_entities_entity_type'), 'graph_entities', ['entity_type'], unique=False)
    op.create_index('idx_entity_name_type', 'graph_entities', ['name', 'entity_type'], unique=False)

    # Recreate graph_relationships
    op.create_table('graph_relationships',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.Column('predicate', sa.String(length=128), nullable=False),
        sa.Column('object_id', sa.Integer(), nullable=False),
        sa.Column('strength', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_graph_relationships_subject_id'), 'graph_relationships', ['subject_id'], unique=False)
    op.create_index(op.f('ix_graph_relationships_predicate'), 'graph_relationships', ['predicate'], unique=False)
    op.create_index(op.f('ix_graph_relationships_object_id'), 'graph_relationships', ['object_id'], unique=False)
    op.create_index('idx_rel_triple', 'graph_relationships', ['subject_id', 'predicate', 'object_id'], unique=False)
    op.create_index('idx_rel_predicate', 'graph_relationships', ['predicate'], unique=False)
