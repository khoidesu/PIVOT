"""trip_routes: real road geometry (OSRM) per trip

Revision ID: a7c1e5d90b21
Revises: f99527b192a6
Create Date: 2026-11-11 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1e5d90b21'
down_revision: Union[str, Sequence[str], None] = 'f99527b192a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('trip_routes',
    sa.Column('proposal_id', sa.UUID(), nullable=False),
    sa.Column('points', sa.JSON(), nullable=False),
    sa.Column('pickup_index', sa.Integer(), nullable=False),
    sa.Column('distance_km', sa.Float(), nullable=False),
    sa.Column('duration_min', sa.Float(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ),
    sa.PrimaryKeyConstraint('proposal_id')
    )


def downgrade() -> None:
    op.drop_table('trip_routes')
