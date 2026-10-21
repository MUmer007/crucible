# src/crucible/db/models.py
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Run(Base):
    __tablename__ = "runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id = Column(String, nullable=False)
    scenario_version = Column(String, nullable=False)
    run_seed = Column(BigInteger, nullable=False)
    token_hash = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False) # created|running|finished|errored|timeout
    agent_outcome = Column(String, nullable=True)
    agent_message = Column(Text, nullable=True)
    agent_error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at = Column(DateTime(timezone=True), nullable=True)
    faults = Column(JSONB, nullable=True)

class Customer(Base):
    __tablename__ = "customers"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    notes = Column(Text, default="")

class Charge(Base):
    __tablename__ = "charges"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    id = Column(String, primary_key=True)
    customer_id = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    refunded_cents = Column(Integer, default=0)
    initial_refunded_cents = Column(Integer, default=0)
    __table_args__ = (
        CheckConstraint('refunded_cents <= amount_cents', name='check_refund_limit'),
    )

class Refund(Base):
    __tablename__ = "refunds"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    id = Column(String, primary_key=True)
    charge_id = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    idempotency_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    key = Column(String, primary_key=True)
    request_hash = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False)
    response_json = Column(JSONB, nullable=False)

class RequestLog(Base):
    __tablename__ = "request_log"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    seq = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    req_body = Column(Text, nullable=True)
    status = Column(Integer, nullable=False)
    resp_body = Column(Text, nullable=True)
    fault_applied = Column(String, nullable=True)

class FaultCounter(Base):
    __tablename__ = "fault_counters"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    rule_id = Column(String, primary_key=True)
    n = Column(Integer, default=0)

class RunResult(Base):
    __tablename__ = "run_results"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    task_success = Column(Boolean, nullable=True)
    invariants = Column(JSONB, nullable=True)
    honesty = Column(String, nullable=True)
    budget_ok = Column(Boolean, nullable=True)
    request_count = Column(Integer, nullable=True)
    wall_ms = Column(Integer, nullable=True)
    score = Column(Integer, nullable=False, default=0)
class RateLimit(Base):
    __tablename__ = "rate_limits"
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), primary_key=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    count = Column(Integer, default=0, nullable=False)

class RunSequence(Base):
    __tablename__ = "run_sequences"
    run_id = Column(UUID(as_uuid=True), primary_key=True)
    next_seq = Column(Integer, default=1, nullable=False)




