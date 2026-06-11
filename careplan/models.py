"""The four tables -- the database schema we designed.

Patient          Provider
      | one-to-many   | one-to-many
            Order
                  | one-to-one
            CarePlan

Orders don't store the patient/provider names, only their ids (foreign keys).
A rename touches just one row, and duplicate names aren't a problem.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careplan.db import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    mrn: Mapped[str] = mapped_column(unique=True, index=True)  # unique patient identifier
    dob: Mapped[str] = mapped_column(default="")               # date of birth (used for duplicate detection)


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    npi: Mapped[str] = mapped_column(unique=True, index=True)  # provider's national unique identifier


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))   # foreign key -> Patient
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))  # foreign key -> Provider
    medication_name: Mapped[str]
    primary_diagnosis: Mapped[str]
    patient_records: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())  # used for the "same day" check

    patient: Mapped["Patient"] = relationship()
    provider: Mapped["Provider"] = relationship()
    care_plan: Mapped["CarePlan"] = relationship(back_populates="order", uselist=False)


class CarePlan(Base):
    __tablename__ = "care_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))  # foreign key -> Order
    content: Mapped[str] = mapped_column(Text, default="")
    # status: synchronous today, so generation goes straight to completed.
    # The async version will start using pending/processing.
    status: Mapped[str] = mapped_column(default="pending")

    order: Mapped["Order"] = relationship(back_populates="care_plan")
